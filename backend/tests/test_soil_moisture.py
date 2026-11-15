"""County topsoil moisture summary (offline)."""
from shapely.geometry import box

from fieldshift.core import soil_moisture as sm


def test_week_mean_uses_cells_inside_the_region_and_drops_bad_values():
    region = box(-118, 46, -117, 47)
    grid = {"values": [0.1, 0.3, None, -9999, 0.2], "lons": [-117.5, -116.5, -117.5, -117.5, -117.2],
            "lats": [46.5, 46.5, 46.5, 46.5, 46.9]}
    assert sm.week_mean(grid, region) == 0.15000000000000002 or abs(sm.week_mean(grid, region) - 0.15) < 1e-9


def test_seasonal_means_and_text():
    weekly = {2020: [("2020-05-04", 0.20), ("2020-06-01", 0.18), ("2020-07-06", 0.16), ("2020-08-03", 0.01)],
              2021: [("2021-05-03", 0.10), ("2021-06-07", 0.08), ("2021-07-05", 0.06)],
              2022: [("2022-05-02", 0.25)]}
    out = sm.seasonal(weekly, (5, 7), 2021, min_weeks=2)
    years = {r["year"]: r for r in out["years"]}
    assert abs(years[2020]["mean"] - 0.18) < 1e-9  # August is outside the season
    assert years[2022]["mean"] is None  # too few weeks
    assert out["driest_year"] == 2021 and "the driest season was 2021 (8%)" in out["text"]
