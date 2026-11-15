"""US Drought Monitor summary (offline)."""
from __future__ import annotations

import pytest

from fieldshift.core import drought


def row(date, none, d0, d1=0, d2=0, d3=0, d4=0):
    return {"date": date, "none": none, "d0": d0, "d1": d1, "d2": d2, "d3": d3, "d4": d4}


def test_summary_worst_class_per_crop_year_and_latest():
    raw = {"rows": [
        row("2020-10-06", 100, 0),
        row("2021-07-27", 0, 100, 100, 100, 100, 100),
        row("2021-09-07", 0, 100, 100, 60, 10, 0),  # crop year 2022
        row("2026-11-10", 0, 100, 100, 83.02, 0, 0),
        {"date": "garbage"}, row("2019-01-01", 0, 150),  # malformed / out of range: dropped
    ]}
    s = drought.summarise(raw, highlight_year=2021)
    years = {y["year"]: y for y in s["years"]}
    assert years[2021]["worst_class"] == "d4" and years[2021]["peak_date"] == "2021-07-27"
    assert years[2022]["worst_class"] == "d2"  # D3 covers only 10%
    assert s["extreme_years"] == [2021]
    assert "100% of Whitman County was in exceptional drought (D4)" in s["highlight_text"]
    assert s["latest"]["worst_class"] == "d2" and "83% of the county" in s["latest"]["text"]
    assert 2019 not in years


def test_empty_is_an_error():
    with pytest.raises(ValueError):
        drought.summarise({"rows": []})
