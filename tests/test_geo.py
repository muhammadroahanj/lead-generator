import pytest

from config.enums import Depth
from geo.areas import area_query, candidate_areas, rank_subareas
from geo.grid import build_grid, km_to_deg_lat, km_to_deg_lng, suggested_zoom
from geo.models import SearchUnit, Target
from geo.parsing import (
    parse_at_coords,
    parse_data_coords,
    parse_place_href,
    parse_place_id,
)
from geo.plan import build_search_plan

HOUSTON = Target(raw="Houston TX", display_name="Houston, TX, USA",
                 lat=29.7604, lng=-95.3698, zoom=11, region="TX")

US_ADDRESSES = [
    "123 Main St, Katy, TX 77494",
    "456 Oak Ave, Katy, TX 77494",
    "789 Pine Rd, Sugar Land, TX 77478",
    "12 Elm Dr, Sugar Land, TX 77478",
    "9 Birch Ln, Pearland, TX 77584",
    "3 Cedar Ct, Houston, TX 77002",
]

PK_ADDRESSES = [
    "12 Main Blvd, Gulberg III, Lahore, Punjab",
    "44 MM Alam Rd, Gulberg III, Lahore, Punjab",
    "8 Commercial Area, DHA Phase 5, Lahore, Punjab",
]


class TestParsing:
    def test_parse_at_coords(self):
        url = "https://www.google.com/maps/search/plumbers/@29.7604267,-95.3698028,13z"
        assert parse_at_coords(url) == (29.7604267, -95.3698028, 13.0)

    def test_parse_at_coords_without_zoom(self):
        lat, lng, zoom = parse_at_coords("https://maps.google.com/@1.5,-2.5")
        assert (lat, lng, zoom) == (1.5, -2.5, None)

    @pytest.mark.parametrize("url", [None, "", "https://google.com/maps", "@999,999,13z"])
    def test_parse_at_coords_rejects_junk(self, url):
        assert parse_at_coords(url) == (None, None, None)

    def test_parse_place_id_hex(self):
        href = "/maps/place/Joes/@29.7,-95.3,17z/data=!4m6!3m5!1s0x8640b8b4488d8501:0xca0d02def365053b"
        assert parse_place_id(href) == "0x8640b8b4488d8501:0xca0d02def365053b"

    def test_parse_place_href_returns_all_three(self):
        href = "/maps/place/X/@29.76,-95.36,17z/data=!3m1!4b1!4m5!1s0x123abc:0x456def"
        place_id, lat, lng = parse_place_href(href)
        assert place_id == "0x123abc:0x456def"
        assert (lat, lng) == (29.76, -95.36)

    def test_parse_place_href_reads_real_result_link(self):
        # Real result hrefs carry no "@" fragment at all — the business's own
        # coordinates live in the data= blob as !3d<lat>!4d<lng>.
        href = (
            "https://www.google.com/maps/place/Beyond+Wow+Plumbing/data="
            "!4m7!3m6!1s0x8644cb2f840615a7:0x8cd2f981d6780fda"
            "!8m2!3d30.3578911!4d-97.7482485!16s%2Fg%2F11fq389yls"
        )
        place_id, lat, lng = parse_place_href(href)
        assert place_id == "0x8644cb2f840615a7:0x8cd2f981d6780fda"
        assert lat == 30.3578911
        assert lng == -97.7482485

    def test_parse_data_coords_rejects_out_of_range(self):
        assert parse_data_coords("!3d999!4d999") == (None, None)
        assert parse_data_coords(None) == (None, None)

    def test_parse_place_href_tolerates_missing_data(self):
        assert parse_place_href(None) == (None, None, None)


class TestAreaDiscovery:
    def test_candidate_areas_drops_street_city_and_state(self):
        areas = candidate_areas("123 Main St, Katy, TX 77494", city="Houston, TX, USA", region="TX")
        assert areas == ["Katy"]

    def test_city_is_never_its_own_subarea(self):
        # The city arrives as "Houston, TX, USA", so each part must be excluded.
        areas = candidate_areas("3 Cedar Ct, Houston, TX 77002", city="Houston, TX, USA", region="TX")
        assert areas == []

    def test_rank_subareas_orders_by_frequency(self):
        areas = rank_subareas(US_ADDRESSES, city="Houston, TX, USA", region="TX",
                              max_areas=10, include_postcodes=False)
        assert areas[:2] == ["Katy", "Sugar Land"]
        assert "Houston" not in areas

    def test_rank_subareas_includes_postcodes(self):
        areas = rank_subareas(US_ADDRESSES, city="Houston, TX, USA", region="TX", max_areas=10)
        assert "77494" in areas

    def test_rank_subareas_respects_max(self):
        areas = rank_subareas(US_ADDRESSES, city="Houston, TX, USA", region="TX", max_areas=2)
        assert len(areas) == 2

    def test_rank_subareas_falls_back_when_nothing_repeats(self):
        # A single sighting still beats degrading silently to city depth.
        areas = rank_subareas(["1 A St, Rarelyville, TX 70000"], city="Houston, TX, USA",
                              region="TX", min_count=2)
        assert "Rarelyville" in areas

    def test_rank_subareas_handles_no_addresses(self):
        assert rank_subareas([], city="Houston") == []

    def test_works_outside_the_us(self):
        areas = rank_subareas(PK_ADDRESSES, city="Lahore, Pakistan", region="Punjab",
                              max_areas=5, include_postcodes=False)
        assert "Gulberg III" in areas
        assert "Lahore" not in areas
        assert "Punjab" not in areas

    @pytest.mark.parametrize("area,city,expected", [
        ("Katy", "Houston, TX, USA", "Katy, TX, USA"),
        ("Gulberg III", "Lahore, Pakistan", "Gulberg III, Pakistan"),
        ("77494", "Houston, TX, USA", "77494"),      # postcodes stand alone
        ("Katy", "", "Katy"),
        ("Houston", "Houston, TX, USA", "Houston, TX, USA"),
    ])
    def test_area_query(self, area, city, expected):
        assert area_query(area, city) == expected


class TestGrid:
    def test_grid_size(self):
        assert len(build_grid(29.76, -95.36, rows=3, cols=4)) == 12

    def test_grid_is_centred_on_the_target(self):
        tiles = build_grid(29.76, -95.36, span_km=18, rows=3, cols=3)
        centre = tiles[4]  # middle of a 3x3
        assert centre["lat"] == pytest.approx(29.76, abs=1e-6)
        assert centre["lng"] == pytest.approx(-95.36, abs=1e-6)

    def test_grid_tiles_are_labelled(self):
        tiles = build_grid(0, 0, rows=2, cols=2)
        assert [t["tile"] for t in tiles] == ["r1c1", "r1c2", "r2c1", "r2c2"]

    def test_grid_spans_the_requested_distance(self):
        tiles = build_grid(29.76, -95.36, span_km=18, rows=3, cols=1)
        span_deg = tiles[0]["lat"] - tiles[-1]["lat"]
        # 3 rows: centre-to-centre distance is 2/3 of the total span.
        assert span_deg == pytest.approx(km_to_deg_lat(18) * 2 / 3, rel=1e-3)

    def test_longitude_degrees_widen_near_the_equator(self):
        assert km_to_deg_lng(10, at_lat=0) < km_to_deg_lng(10, at_lat=60)

    def test_grid_survives_the_poles(self):
        tiles = build_grid(89.99, 0, span_km=10, rows=2, cols=2)
        assert len(tiles) == 4

    def test_single_cell_grid(self):
        tiles = build_grid(10, 20, rows=1, cols=1)
        assert tiles == [{"lat": 10.0, "lng": 20.0, "tile": "r1c1", "row": 1, "col": 1}]

    def test_suggested_zoom_tightens_for_small_cells(self):
        assert suggested_zoom(3, 3, 3) > suggested_zoom(60, 3, 3)


class TestSearchUnit:
    def test_plain_url(self):
        unit = SearchUnit(category="plumbers", query="plumbers in Katy, TX")
        assert unit.url == "https://www.google.com/maps/search/plumbers+in+Katy%2C+TX"

    def test_tile_url_pins_coordinates(self):
        unit = SearchUnit(category="plumbers", query="plumbers in Houston",
                          lat=29.76, lng=-95.36, zoom=14, tile="r1c1")
        assert "@29.7600000,-95.3600000,14z" in unit.url

    def test_keys_are_distinct_per_scope(self):
        city = SearchUnit(category="x", query="q", city="Houston")
        area = SearchUnit(category="x", query="q", city="Houston", area="Katy")
        tile = SearchUnit(category="x", query="q", city="Houston", tile="r1c1")
        assert len({city.key, area.key, tile.key}) == 3

    def test_labels_describe_the_scope(self):
        assert SearchUnit(category="plumbers", query="q", city="Houston").label == "plumbers in Houston"
        assert SearchUnit(category="plumbers", query="q", city="H", area="Katy").label == "plumbers in Katy"


class TestPlan:
    def test_city_depth(self):
        units = build_search_plan(HOUSTON, ["plumbers", "dentists"], Depth.CITY)
        assert len(units) == 2
        assert units[0].query == "plumbers in Houston, TX, USA"

    def test_areas_depth_multiplies_by_area_count(self):
        units = build_search_plan(HOUSTON, ["plumbers"], Depth.AREAS,
                                  areas=["Katy", "Sugar Land", "Pearland"])
        assert len(units) == 3
        assert {u.area for u in units} == {"Katy", "Sugar Land", "Pearland"}

    def test_areas_depth_falls_back_to_city_when_none_found(self):
        units = build_search_plan(HOUSTON, ["plumbers"], Depth.AREAS, areas=[])
        assert len(units) == 1
        assert units[0].area is None

    def test_grid_depth(self):
        units = build_search_plan(HOUSTON, ["plumbers"], Depth.GRID,
                                  grid_rows=3, grid_cols=3)
        assert len(units) == 9
        assert all(u.lat is not None for u in units)

    def test_grid_depth_without_coordinates_falls_back(self):
        target = Target(raw="Nowhere", display_name="Nowhere")
        units = build_search_plan(target, ["plumbers"], Depth.GRID)
        assert len(units) == 1
        assert units[0].lat is None

    def test_no_categories_means_no_units(self):
        assert build_search_plan(HOUSTON, [], Depth.CITY) == []

    def test_unit_keys_are_unique_across_a_grid_plan(self):
        units = build_search_plan(HOUSTON, ["plumbers", "dentists"], Depth.GRID,
                                  grid_rows=2, grid_cols=2)
        assert len({u.key for u in units}) == len(units)
