"""Interactive setup wizard.

Replaces the three raw ``input()`` calls the scraper used to configure itself
with. Everything the run needs is collected here and returned as a RunConfig.
"""

import logging

import questionary
from questionary import Choice
from rich.panel import Panel
from rich.table import Table

from config.categories import CATEGORIES
from config.enums import Depth, LeadProfile
from config.metros import METROS
from config.runconfig import RunConfig
from ui.console import console

logger = logging.getLogger(__name__)

# Rough per-unit cost used only to give the user a sense of scale before they
# commit to a multi-hour run.
SECONDS_PER_UNIT_ESTIMATE = 6.5 * 60
CUSTOM_CATEGORY = "__custom_category__"


class WizardCancelled(Exception):
    """The user backed out of the wizard (Ctrl-C or ESC)."""


def _ask(prompt):
    """Run a questionary prompt, treating cancellation as an abort."""
    answer = prompt.ask()
    if answer is None:
        raise WizardCancelled()
    return answer


def _banner():
    console.print(
        Panel.fit(
            "[bold cyan]Google Maps Lead Scraper[/bold cyan]\n"
            "[dim]Point it at any city or area, pick how deep to dig.[/dim]",
            border_style="cyan",
        )
    )


def _ask_target() -> str:
    """Free-form place input, with the metro presets as a shortcut."""
    mode = _ask(questionary.select(
        "What do you want to scrape?",
        choices=[
            Choice("Type any city or area (anywhere in the world)", value="free"),
            Choice("Pick from the built-in US metro presets", value="preset"),
        ],
    ))

    if mode == "preset":
        choices = [Choice(m["name"], value=m["search_term"]) for m in METROS]
        return _ask(questionary.select("Which metro?", choices=choices))

    while True:
        value = _ask(questionary.text(
            "City or area:",
            instruction="e.g. 'Austin TX', 'Lahore', 'Gulberg, Lahore', 'Camden, London'",
        )).strip()
        if value:
            return value
        console.print("[yellow]Please enter a place.[/yellow]")


def _ask_depth() -> Depth:
    choices = [
        Choice(f"{d.label} — {d.blurb}", value=d)
        for d in (Depth.AREAS, Depth.CITY, Depth.GRID)
    ]
    return _ask(questionary.select(
        "How deep should the search go?",
        choices=choices,
        instruction="(Google caps each query at ~120 results, so narrower queries = more leads)",
    ))


def _ask_categories() -> list[str]:
    choices = [Choice(c, value=c) for c in CATEGORIES]
    choices.append(Choice("Enter a custom keyword...", value=CUSTOM_CATEGORY))
    while True:
        selected = _ask(questionary.checkbox(
            "Which business categories?",
            choices=choices,
            instruction="(space to toggle, enter to confirm)",
        ))
        if CUSTOM_CATEGORY in selected:
            selected.remove(CUSTOM_CATEGORY)
            custom = _ask(questionary.text(
                "Custom business keyword:",
                instruction="e.g. 'solar panel installer'",
            )).strip()
            if custom and custom not in selected:
                selected.append(custom)
        if selected:
            return selected
        console.print("[yellow]Pick a category or enter a custom keyword.[/yellow]")


def _ask_profile() -> LeadProfile:
    choices = [
        Choice(f"{p.label} — {p.blurb}", value=p)
        for p in (LeadProfile.NO_WEBSITE, LeadProfile.NO_EMAIL, LeadProfile.ALL)
    ]
    return _ask(questionary.select("What counts as a qualified lead?", choices=choices))


def _ask_float(message: str, default: float) -> float:
    while True:
        raw = _ask(questionary.text(message, default=str(default))).strip()
        try:
            return float(raw)
        except ValueError:
            console.print("[yellow]Enter a number.[/yellow]")


def _ask_int(message: str, default: int) -> int:
    while True:
        raw = _ask(questionary.text(message, default=str(default))).strip()
        try:
            return int(raw)
        except ValueError:
            console.print("[yellow]Enter a whole number.[/yellow]")


def _estimate(units: int) -> str:
    total = units * SECONDS_PER_UNIT_ESTIMATE
    hours = total / 3600
    if hours < 1:
        return f"~{total / 60:.0f} min"
    return f"~{hours:.1f} hours"


def _confirm_summary(cfg: RunConfig, estimated_units: int) -> bool:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Target", cfg.target_input)
    table.add_row("Depth", cfg.depth.label)
    table.add_row("Categories", f"{len(cfg.categories)}: " + ", ".join(cfg.categories[:6])
                  + ("..." if len(cfg.categories) > 6 else ""))
    table.add_row("Lead profile", cfg.profile.label)
    table.add_row("Min rating / reviews", f"{cfg.min_rating} / {cfg.min_reviews}")
    if cfg.depth is Depth.GRID:
        table.add_row("Grid", f"{cfg.grid_rows}x{cfg.grid_cols} over {cfg.grid_span_km:g} km")
    if cfg.depth is Depth.AREAS:
        table.add_row("Max sub-areas", str(cfg.max_subareas))
    if cfg.max_results_per_unit:
        table.add_row("Result cap", f"{cfg.max_results_per_unit} per search")
    table.add_row("Browser", "headless" if cfg.headless else "visible")
    if cfg.concurrency > 1:
        table.add_row("Parallel browsers", str(cfg.concurrency))
    if cfg.proxy:
        table.add_row("Proxy", cfg.proxy)
    table.add_row("Output", str(cfg.output.root))
    table.add_row(
        "Estimated work",
        f"~{estimated_units} searches, {_estimate(estimated_units)}",
    )

    console.print(Panel(table, title="Run plan", border_style="cyan"))
    return bool(_ask(questionary.confirm("Start scraping?", default=True)))


def _estimated_units(cfg: RunConfig) -> int:
    """Predict the plan size so the confirmation screen means something."""
    categories = max(1, len(cfg.categories))
    if cfg.depth is Depth.AREAS:
        return categories * max(1, cfg.max_subareas)
    if cfg.depth is Depth.GRID:
        return categories * max(1, cfg.grid_rows * cfg.grid_cols)
    return categories


def run_wizard(base: RunConfig | None = None) -> RunConfig:
    """Collect a full run configuration interactively.

    Raises ``WizardCancelled`` if the user backs out.
    """
    cfg = base or RunConfig()
    _banner()

    cfg.target_input = _ask_target()
    cfg.depth = _ask_depth()
    cfg.categories = _ask_categories()
    cfg.profile = _ask_profile()

    if _ask(questionary.confirm("Adjust quality thresholds?", default=False)):
        cfg.min_rating = _ask_float("Minimum rating (0 to disable):", cfg.min_rating)
        cfg.min_reviews = _ask_int("Minimum reviews (0 to disable):", cfg.min_reviews)
        cfg.require_phone = bool(_ask(questionary.confirm(
            "Require a phone number?", default=cfg.require_phone
        )))

    if cfg.depth is Depth.AREAS:
        cfg.max_subareas = _ask_int(
            "How many sub-areas to search?", cfg.max_subareas
        )
    elif cfg.depth is Depth.GRID:
        cfg.grid_rows = _ask_int("Grid rows:", cfg.grid_rows)
        cfg.grid_cols = _ask_int("Grid columns:", cfg.grid_cols)
        cfg.grid_span_km = _ask_float("Area to cover (km across):", cfg.grid_span_km)

    cap = _ask(questionary.text(
        "Max results per search (blank = no cap):", default=""
    )).strip()
    cfg.max_results_per_unit = int(cap) if cap.isdigit() and int(cap) > 0 else None

    cfg.headless = bool(_ask(questionary.confirm(
        "Run headless (browser hidden)?", default=cfg.headless
    )))

    cfg.concurrency = _ask_int(
        "Browsers to run in parallel (1 is safest; higher = faster but more block risk):",
        cfg.concurrency,
    )

    if _ask(questionary.confirm("Use a proxy?", default=bool(cfg.proxy))):
        cfg.proxy = _ask(questionary.text(
            "Proxy URL:",
            default=cfg.proxy or "",
            instruction="e.g. http://user:pass@host:port",
        )).strip() or None
    else:
        cfg.proxy = None

    if not _confirm_summary(cfg, _estimated_units(cfg)):
        raise WizardCancelled()

    return cfg


def default_config_notice(cfg: RunConfig) -> None:
    """Print what a non-interactive run is about to do."""
    console.print(
        f"[cyan]Scraping[/cyan] [bold]{cfg.target_input}[/bold] "
        f"| depth={cfg.depth.value} | {len(cfg.categories)} categories "
        f"| profile={cfg.profile.value}"
    )
