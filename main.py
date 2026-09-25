"""
Google Maps Lead Scraper — entry point.

Point it at any city or area, choose how deep to dig, and watch it run.

Usage:
    python main.py                                      # interactive wizard + dashboard
    python main.py --city "Austin TX" --categories plumbers electricians
    python main.py --city Lahore --depth areas --profile no_website
    python main.py --doctor                             # check selectors against live Maps
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path so the package imports resolve when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings                                    # noqa: E402
from config.categories import CATEGORIES                       # noqa: E402
from config.enums import Depth, LeadProfile                    # noqa: E402
from config.metros import METROS                               # noqa: E402
from config.paths import OutputPaths                           # noqa: E402
from config.runconfig import RunConfig                         # noqa: E402
from reporting import format_duration                          # noqa: E402
from runner import ScraperRun                                  # noqa: E402
from ui.console import console, is_interactive                 # noqa: E402
from ui.dashboard import make_reporter                         # noqa: E402

logger = logging.getLogger("gmaps_scraper")


def setup_logging(log_file: Path, quiet_console: bool = False):
    """Console at INFO (unless the dashboard owns the terminal), file at DEBUG."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    if not quiet_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"
        ))
        root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)-7s | %(message)s"
    ))
    root_logger.addHandler(file_handler)

    # Playwright is extremely chatty at DEBUG.
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Google Maps Lead Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                     Interactive wizard (recommended)
  python main.py --city "Austin TX" --depth areas    Split the city into sub-areas
  python main.py --city Lahore --categories dentists Non-US works the same way
  python main.py --city "Miami FL" --depth grid --grid 4x4
  python main.py --doctor                            Check selectors against live Maps
  python main.py --list-categories                   Show the built-in categories
""",
    )

    target = parser.add_argument_group("target")
    target.add_argument("--city", "--area", dest="city", type=str,
                        help="City or area to scrape. Anything Google Maps understands.")
    target.add_argument("--metro", type=str,
                        help="Use a built-in US metro preset by name, e.g. --metro Houston")
    target.add_argument("--categories", nargs="+", metavar="CAT",
                        help="Business categories. Defaults to the built-in list.")
    target.add_argument("--depth", choices=[d.value for d in Depth], default=None,
                        help="city = 1 search per category; areas = per sub-area; grid = per map tile")

    quality = parser.add_argument_group("lead quality")
    quality.add_argument("--profile", choices=[p.value for p in LeadProfile], default=None,
                         help="Which businesses count as qualified leads")
    quality.add_argument("--min-rating", type=float, default=None)
    quality.add_argument("--min-reviews", type=int, default=None)
    quality.add_argument("--no-require-phone", action="store_true",
                         help="Qualify leads even without a phone number")
    quality.add_argument("--no-website-crawl", action="store_true",
                         help="Never open business websites to hunt for emails/socials (much faster)")

    scope = parser.add_argument_group("scope")
    scope.add_argument("--max-areas", type=int, default=None,
                       help=f"Sub-areas to search at depth=areas (default {settings.MAX_SUBAREAS})")
    scope.add_argument("--grid", type=str, default=None, metavar="RxC",
                       help="Grid size at depth=grid, e.g. 3x3")
    scope.add_argument("--grid-span", type=float, default=None, metavar="KM",
                       help=f"Width of the grid in km (default {settings.GRID_SPAN_KM:g})")
    scope.add_argument("--max-results", type=int, default=None,
                       help="Cap results per search")

    runtime = parser.add_argument_group("runtime")
    runtime.add_argument("--headless", action="store_true", help="Hide the browser window")
    runtime.add_argument("--proxy", type=str, default=None,
                         help="Proxy URL, e.g. http://user:pass@host:port")
    runtime.add_argument("--output", type=str, default=None, help="Output directory")
    runtime.add_argument("--concurrency", type=int, default=None, metavar="N",
                         help="Run N browsers in parallel (default 1). Faster, but N times "
                              "the request rate and a correspondingly higher block risk.")
    runtime.add_argument("--no-resume", action="store_true",
                         help="Ignore saved progress and re-scrape everything")
    runtime.add_argument("--no-tui", action="store_true", help="Plain log output, no dashboard")
    runtime.add_argument("--yes", "-y", action="store_true",
                         help="Skip the wizard and run with defaults")

    tools = parser.add_argument_group("tools")
    tools.add_argument("--doctor", action="store_true",
                       help="Check every selector against live Google Maps and exit")
    tools.add_argument("--list-categories", action="store_true",
                       help="Print the built-in categories and exit")

    return parser.parse_args(argv)


def _resolve_metro(name: str) -> str | None:
    """Look up a metro preset by name or search term, case-insensitively."""
    wanted = name.strip().lower()
    for metro in METROS:
        if wanted in (metro["name"].lower(), metro["search_term"].lower()):
            return metro["search_term"]
    matches = [m for m in METROS if wanted in m["name"].lower()]
    return matches[0]["search_term"] if len(matches) == 1 else None


def _parse_grid(value: str) -> tuple[int, int] | None:
    """Parse '3x3' into (3, 3)."""
    for sep in ("x", "X", ","):
        if sep in value:
            left, _, right = value.partition(sep)
            if left.strip().isdigit() and right.strip().isdigit():
                return int(left), int(right)
    return None


def config_from_args(args) -> RunConfig:
    """Build a RunConfig from CLI flags, falling back to settings defaults."""
    cfg = RunConfig()

    if args.output:
        cfg.output = OutputPaths(root=Path(args.output))

    if args.metro:
        resolved = _resolve_metro(args.metro)
        if not resolved:
            raise SystemExit(
                f"Unknown metro '{args.metro}'. Run --list-categories to see the "
                "category list, or pass --city to scrape any place directly."
            )
        cfg.target_input = resolved
    if args.city:
        cfg.target_input = args.city
    elif not cfg.target_input and settings.CITY:
        # Lets Docker/CI set a target without overriding the command.
        cfg.target_input = settings.CITY

    if args.categories:
        cfg.categories = args.categories
    elif settings.CATEGORIES_OVERRIDE:
        cfg.categories = settings.CATEGORIES_OVERRIDE
    else:
        cfg.categories = list(CATEGORIES)

    if args.depth:
        cfg.depth = Depth(args.depth)
    elif settings.DEPTH:
        cfg.depth = Depth(settings.DEPTH)
    if args.profile:
        cfg.profile = LeadProfile(args.profile)
    if args.min_rating is not None:
        cfg.min_rating = args.min_rating
    if args.min_reviews is not None:
        cfg.min_reviews = args.min_reviews
    if args.no_require_phone:
        cfg.require_phone = False
    if args.no_website_crawl:
        cfg.fetch_website_email = False
    if args.max_areas is not None:
        cfg.max_subareas = args.max_areas
    if args.grid:
        parsed = _parse_grid(args.grid)
        if not parsed:
            raise SystemExit(f"Could not parse --grid '{args.grid}'. Use e.g. 3x3.")
        cfg.grid_rows, cfg.grid_cols = parsed
    if args.grid_span is not None:
        cfg.grid_span_km = args.grid_span
    if args.max_results is not None:
        cfg.max_results_per_unit = args.max_results
    if args.headless:
        cfg.headless = True
    if args.proxy:
        cfg.proxy = args.proxy
    if args.concurrency is not None:
        cfg.concurrency = args.concurrency

    cfg.resume = not args.no_resume
    cfg.tui = not args.no_tui
    return cfg


def print_summary(summary: dict, aborted: str | None):
    """Final report, printed after the dashboard has released the terminal."""
    from rich.panel import Panel
    from rich.table import Table

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Target", f"{summary['target']}  (depth={summary['depth']})")
    table.add_row("Searches", (
        f"{summary['units_done']} done, {summary['units_failed']} failed, "
        f"{summary['units_skipped']} skipped, of {summary['units_total']}"
    ))
    table.add_row("Businesses found", str(summary["found"]))
    table.add_row("Unique / duplicates", f"{summary['unique']} / {summary['duplicates']}")
    table.add_row("Qualified leads", f"[green]{summary['qualified']}[/green]")
    if summary["blocks"]:
        table.add_row("Blocks hit", f"[yellow]{summary['blocks']}[/yellow]")
    table.add_row("Rows in leads_raw.csv", str(summary["raw_rows"]))
    table.add_row("Rows in leads_qualified.csv", str(summary["qualified_rows"]))
    table.add_row("Dedup pool", str(summary["dedup_pool"]))
    table.add_row("Elapsed", format_duration(summary["elapsed"]))

    border = "yellow" if aborted else "green"
    console.print(Panel(table, title="Run complete", border_style=border))
    if aborted:
        console.print(f"[yellow]{aborted}[/yellow]")
        console.print("[dim]Progress was saved — re-run the same command to resume.[/dim]")


def prepare_config(args) -> tuple[RunConfig | None, int | None]:
    """Build config and run terminal prompts before asyncio owns the thread."""
    cfg = config_from_args(args)

    wants_wizard = not cfg.target_input and not args.yes and is_interactive()
    if wants_wizard:
        from ui.wizard import WizardCancelled, run_wizard
        try:
            cfg = run_wizard(cfg)
        except (WizardCancelled, KeyboardInterrupt):
            console.print("[yellow]Cancelled.[/yellow]")
            return None, 130

    if not cfg.target_input:
        console.print(
            "[red]No target specified.[/red] Pass [bold]--city \"Austin TX\"[/bold] "
            "(or --metro Houston), or run without [bold]-y[/bold] for the setup wizard."
        )
        return None, 2

    return cfg, None


async def run(args, cfg: RunConfig | None = None) -> int:
    """Async half of the entry point. Arg parsing happens before the loop
    starts, so argparse's SystemExit never has to unwind through asyncio."""
    if args.doctor:
        setup_logging(OutputPaths(root=settings.OUTPUT_DIR).log_file)
        from scraper.doctor import run_doctor
        ok = await run_doctor(headless=args.headless)
        return 0 if ok else 1

    if cfg is None:
        cfg, exit_code = prepare_config(args)
        if exit_code is not None:
            return exit_code
        assert cfg is not None

    reporter = make_reporter(cfg.tui)
    uses_dashboard = reporter.__class__.__name__ == "DashboardReporter"
    setup_logging(cfg.output.log_file, quiet_console=uses_dashboard)

    if not uses_dashboard:
        from ui.wizard import default_config_notice
        default_config_notice(cfg)

    run_obj = ScraperRun(cfg, reporter)
    stats = await run_obj.execute()
    print_summary(run_obj.summary(), stats.aborted_reason)

    return 0 if not stats.aborted_reason else 1


def main(argv=None):
    args = parse_args(argv)

    if args.list_categories:
        for category in CATEGORIES:
            console.print(f"  {category}")
        raise SystemExit(0)

    try:
        cfg = None
        if not args.doctor:
            cfg, exit_code = prepare_config(args)
            if exit_code is not None:
                raise SystemExit(exit_code)
        raise SystemExit(asyncio.run(run(args, cfg)))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
