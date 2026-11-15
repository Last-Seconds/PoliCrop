"""The 2050 outlook arithmetic (core/outlook.py): offline, synthetic arrays only."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from fieldshift.core import outlook

F90_K = outlook.f_to_k(90.0)


def _year(n_days=365, cells=2, pr_mm_day=1.0, tmax_k=290.0, tmin_k=280.0):
    pr = np.full((n_days, cells), pr_mm_day / outlook.SECONDS_PER_DAY)
    return pr, np.full((n_days, cells), tmax_k), np.full((n_days, cells), tmin_k)


def test_unit_conversions():
    assert outlook.k_to_f(273.15) == pytest.approx(32.0)
    assert outlook.k_to_f(F90_K) == pytest.approx(90.0)
    assert F90_K == pytest.approx(305.372, abs=1e-3)
    assert outlook.flux_to_mm_day(1.0 / 86400) == pytest.approx(1.0)


@pytest.mark.parametrize("n,april_jul,jun_jul", [(365, 122, 61), (366, 122, 61), (360, 120, 60)])
def test_months_for_each_calendar(n, april_jul, jun_jul):
    m = outlook.months_for_year(n)
    assert len(m) == n and m[0] == 1 and m[-1] == 12
    assert np.isin(m, (4, 5, 6, 7)).sum() == april_jul
    assert np.isin(m, (6, 7)).sum() == jun_jul
    if n == 366:
        assert (m == 2).sum() == 29
    if n == 365:
        assert (m == 3).argmax() == 59  # 1 March is day index 59 in a common year


def test_months_reject_odd_lengths():
    with pytest.raises(ValueError):
        outlook.months_for_year(364)


def test_april_july_precip_is_a_seasonal_sum_of_the_weighted_series():
    pr, tx, tn = _year(pr_mm_day=1.0)
    pr[:, 1] *= 3.0  # second cell is three times wetter
    s = outlook.year_summary(pr, tx, tn, [1.0, 1.0])
    assert s["apr_jul_precip_mm"] == pytest.approx(122 * 2.0)  # mean of 1 and 3 mm/day, 122 days
    s = outlook.year_summary(pr, tx, tn, [3.0, 1.0])  # weights are normalised
    assert s["apr_jul_precip_mm"] == pytest.approx(122 * 1.5)


def test_rain_outside_april_july_does_not_count():
    pr, tx, tn = _year(pr_mm_day=0.0)
    months = outlook.months_for_year(365)
    pr[months == 8] = 10.0 / outlook.SECONDS_PER_DAY
    pr[months == 4] = 2.0 / outlook.SECONDS_PER_DAY
    assert outlook.year_summary(pr, tx, tn, [1, 1])["apr_jul_precip_mm"] == pytest.approx(60.0)


def test_hot_days_count_only_june_july_at_or_above_90f_per_cell():
    pr, tx, tn = _year(tmax_k=300.0)
    months = outlook.months_for_year(365)
    jun = np.flatnonzero(months == 6)
    aug = np.flatnonzero(months == 8)
    tx[jun[:10], 0] = F90_K  # exactly 90 F counts
    tx[jun[10:12], 0] = F90_K - 0.01  # just below does not
    tx[jun[:4], 1] = F90_K + 5
    tx[aug, :] = F90_K + 10  # August is out of season
    s = outlook.year_summary(pr, tx, tn, [1.0, 1.0])
    assert s["hot_days"] == pytest.approx((10 + 4) / 2)  # per-cell counts, then weighted
    assert outlook.year_summary(pr, tx, tn, [1.0, 0.0])["hot_days"] == pytest.approx(10)


def test_mean_temperature_is_mean_of_max_and_min():
    pr, tx, tn = _year(tmax_k=293.15, tmin_k=273.15)
    assert outlook.year_summary(pr, tx, tn, [1, 1])["mean_temp_c"] == pytest.approx(10.0)


def test_year_summary_validates_inputs():
    pr, tx, tn = _year()
    with pytest.raises(ValueError):
        outlook.year_summary(pr, tx[:, :1], tn, [1, 1])  # shapes differ
    with pytest.raises(ValueError):
        outlook.year_summary(pr, tx, tn, [1])  # one weight per cell
    with pytest.raises(ValueError):
        outlook.year_summary(pr, tx, tn, [0, 0])
    bad = tx.copy()
    bad[5, 0] = np.nan
    with pytest.raises(ValueError):
        outlook.year_summary(pr, bad, tn, [1, 1])
    with pytest.raises(ValueError):
        outlook.year_summary(pr, tx - 273.15, tn, [1, 1])  # Celsius passed as kelvin
    with pytest.raises(ValueError):
        outlook.year_summary(pr * 86400 * 100, tx, tn, [1, 1])  # mm/day passed as a flux


def test_window_mean_and_model_change():
    hist = outlook.window_mean([
        {"apr_jul_precip_mm": 100.0, "hot_days": 4.0, "mean_temp_c": 9.0},
        {"apr_jul_precip_mm": 140.0, "hot_days": 6.0, "mean_temp_c": 11.0},
    ])
    assert hist == {"apr_jul_precip_mm": 120.0, "hot_days": 5.0, "mean_temp_c": 10.0}
    fut = {"apr_jul_precip_mm": 132.0, "hot_days": 17.0, "mean_temp_c": 12.5}
    c = outlook.model_change(hist, fut)
    assert c["apr_jul_precip_change_pct"] == pytest.approx(10.0)
    assert c["apr_jul_precip_change_mm"] == pytest.approx(12.0)
    assert c["apr_jul_precip_change_in"] == pytest.approx(12.0 / 25.4)
    assert c["hot_days_change"] == pytest.approx(12.0)
    assert c["mean_temp_change_c"] == pytest.approx(2.5)
    assert c["mean_temp_change_f"] == pytest.approx(4.5)  # a difference: no +32
    with pytest.raises(ValueError):
        outlook.window_mean([])


def test_spread_statistics():
    s = outlook.spread([5, 1, 3, 2, 4])
    assert s == {"median": 3.0, "min": 1.0, "max": 5.0, "p25": 2.0, "p75": 4.0, "n": 5}
    s = outlook.spread([1.0, 2.0, float("nan"), 3.0, 4.0])  # missing values are skipped
    assert s["n"] == 4 and s["median"] == 2.5 and s["p25"] == 1.75
    with pytest.raises(ValueError):
        outlook.spread([])


def test_scenario_summary_and_baseline():
    hist = {"A": {"apr_jul_precip_mm": 100.0, "hot_days": 5.0, "mean_temp_c": 10.0},
            "B": {"apr_jul_precip_mm": 120.0, "hot_days": 7.0, "mean_temp_c": 9.0},
            "C": {"apr_jul_precip_mm": 110.0, "hot_days": 6.0, "mean_temp_c": 11.0}}
    fut = {"A": {"apr_jul_precip_mm": 110.0, "hot_days": 10.0, "mean_temp_c": 12.0},
           "B": {"apr_jul_precip_mm": 108.0, "hot_days": 15.0, "mean_temp_c": 11.0},
           "C": {"apr_jul_precip_mm": 110.0, "hot_days": 9.0, "mean_temp_c": 13.0}}
    changes = {m: outlook.model_change(hist[m], fut[m]) for m in hist}
    s = outlook.scenario_summary(changes)
    assert s["apr_jul_precip_change_pct"]["median"] == 0.0
    assert s["apr_jul_precip_change_pct"]["min"] == -10.0 and s["apr_jul_precip_change_pct"]["max"] == 10.0
    assert s["hot_days_change"]["median"] == 5.0 and s["hot_days_change"]["n"] == 3
    assert s["mean_temp_change_f"]["median"] == pytest.approx(3.6)
    assert s["models_agree_on_precip_sign"] == {"wetter": 1, "drier": 1, "n": 3}
    assert [r["model"] for r in s["per_model"]] == ["A", "B", "C"]
    b = outlook.baseline_summary(hist)
    assert b["apr_jul_precip_mm"] == 110.0
    assert b["apr_jul_precip_in"] == pytest.approx(round(110 / 25.4, 2))
    assert b["mean_temp_f"] == 50.0 and b["hot_days"] == 6.0
    assert b["spread"]["mean_temp_f"]["min"] == pytest.approx(48.2)


def test_outlook_core_is_pure():
    src = (Path(__file__).resolve().parents[1] / "fieldshift" / "core" / "outlook.py").read_text()
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, flags=re.M)
    allowed = {"__future__", "typing", "numpy", ".units"}
    assert set(imports) <= allowed, set(imports) - allowed
