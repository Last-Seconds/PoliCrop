"""Brief 3, part S: what is offered (S1) and how much is on screen (S2)."""
from __future__ import annotations

import datetime as dt

import pytest

from fieldshift.core.content import load_content
from fieldshift.core.geometry import field_from_spec
from fieldshift.core.present import FIRST_LAYER_MAX_WORDS, HEADINGS, word_count
from fieldshift.core.present import closed_words as present_closed_words
from fieldshift.core.service import FieldService, Providers

from .fakes import DATA_DIR, FIELD, FakeCrops, FakeRegion, FakeSoil, FakeVegetation, FakeWeather


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture(scope="module")
def service(content):
    return FieldService(content, Providers(FakeRegion(), FakeCrops(), FakeWeather(short=False), FakeVegetation(),
                                           soil=FakeSoil()), today=dt.date(2026, 11, 14))


@pytest.fixture(scope="module")
def field():
    return field_from_spec({"type": "polygon", "geometry": FIELD})


def closed_words(c: dict) -> int:
    return present_closed_words(c["closed"])


def first_words(c: dict) -> int:
    f = c["first"]
    return word_count(HEADINGS, f["why"], [e["label"] for e in f["evidence"]], [e["text"] for e in f["evidence"]],
                      f["gains"], f["unknowns"], f["check"])


def legume_gaps(crop_ids, content) -> int:
    n = len(crop_ids)
    pos = [i for i, c in enumerate(crop_ids) if content.crop(c).role == "legume"]
    gaps = [n] if len(pos) == 1 else [((b - a) % n) or n for a in pos for b in pos if a != b]
    return min(gaps) if pos else n


@pytest.mark.parametrize("inputs", [{}, {"plan_length": 4}, {"dry_mode": True}, {"priorities": ["nitrogen"]}])
def test_no_option_has_two_legumes_within_three_years(service, field, content, inputs):
    s = service.strategies(field, inputs)
    for o in s["options"] + s["more"]:
        assert legume_gaps(o["crop_ids"], content) >= 3, o["crop_ids"]


@pytest.mark.parametrize("inputs", [{}, {"plan_length": 6}, {"rain_pct": -30, "dry_mode": True}])
def test_screen_word_limits(service, field, inputs):
    s = service.strategies(field, inputs)
    assert len(s["headline"]) == 1 and word_count(s["headline"]) <= 25
    for c in [s["current"]] + s["options"] + s["more"]:
        assert closed_words(c) <= 45, c["closed"]
        assert first_words(c) <= FIRST_LAYER_MAX_WORDS, c["first"]
        assert len(c["first"]["unknowns"]) <= 3
        assert c["closed"]["more_cautions"] == max(0, len(c["cautions"]) - 1)


def test_current_card_holds_the_map_notes_and_same_layout(service, field):
    s = service.strategies(field, {})
    cur = s["current"]
    assert set(cur["closed"]) == set(s["options"][0]["closed"])
    assert "map_notes" in cur["details"]
    assert all("crop map shows" not in h for h in s["headline"])


def test_nothing_is_lost_from_the_details(service, field):
    """Moving things down a layer: the full evidence, unknowns and checks are all still there."""
    s = service.strategies(field, {})
    for c in s["options"]:
        d = c["details"]
        assert {e["measure"] for e in d["evidence"]} == {"water", "soil", "nitrogen", "variety"}
        assert d["unknowns"] and d["check"] and d["why"]
        assert all(e["lines"] for e in d["evidence"])
        assert c["lines"] and c["notes"]["harvests_text"]


def test_kept_options_are_scored_and_marked(service, field, content):
    base = service.strategies(field, {})
    shown = base["options"][0]["crop_ids"]
    custom = ["winter_wheat", "fallow", "spring_wheat"]
    s = service.strategies(field, {"kept": [{"crops": shown, "note": "ask Joe"}, custom, ["nonsense", "x"]]})
    assert s["options"][0]["kept"] is True  # already listed: marked, not repeated
    assert [k["crop_ids"] for k in s["kept"]] == [list(custom)] or \
        sorted(s["kept"][0]["crop_ids"]) == sorted(custom)
    k = s["kept"][0]
    assert k["kept"] and k["closed"]["verdicts"][0]["word"]
    assert "kept" in s["inputs"]["ignored"]


# ---- addendum 2, section A ----------------------------------------------------------------------

def _new(c, cur):
    return {x for x in c["crop_ids"] if x not in cur["crop_ids"] and x != "fallow"}


@pytest.mark.parametrize("inputs", [{}, {"plan_length": 4}, {"priorities": ["variety"]}, {"rain_pct": -30}])
def test_serious_caution_never_first_and_options_differ(service, field, inputs):
    s = service.strategies(field, inputs)
    flags = [any(c.get("serious") for c in o["cautions"]) for o in s["options"]]
    assert flags == sorted(flags)  # no serious option ahead of one without
    if len(s["options"]) == 3:
        assert not set.intersection(*(_new(o, s["current"]) for o in s["options"]))
    for o in s["options"]:  # a serious caution is never hidden behind "more"
        serious = [c["short"] for c in o["cautions"] if c.get("serious")]
        assert o["closed"]["serious"] == serious


def test_headline_names_a_serious_caution(service, field):
    s = service.strategies(field, {})
    for o in s["options"]:
        if o["id"] in s["headline"][0] and any(c.get("serious") for c in o["cautions"]):
            assert "but note" in s["headline"][0]
