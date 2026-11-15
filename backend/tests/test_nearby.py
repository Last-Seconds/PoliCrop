"""Nearby use: cyclic role-pattern shares from a role-sequence histogram (offline)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from fieldshift.core.nearby import NearbyUse, canonical, code_roles

C, F, L, O = "cereal", "fallow", "legume", "oilseed"


def crops(*roles):
    return [SimpleNamespace(role=r) for r in roles]


def payload(seqs: dict[tuple, int], years=(2020, 2021, 2022, 2023, 2024, 2025), mapped=(C, F, L, O, "forage")):
    return {"years": list(years), "sequences": {"|".join(k): v for k, v in seqs.items()},
            "roles_mapped": sorted(mapped), "unknown_token": "?", "pixel_size_m": 30.0, "source": "test"}


HIST = payload({
    (C, F, C, F, C, F): 40,   # wheat-fallow, phase 0
    (F, C, F, C, F, C): 20,   # wheat-fallow, phase 1
    (C, F, C, C, C, F): 5,    # wheat-fallow with one odd year
    (C, C, L, C, C, L): 25,   # cereal-cereal-legume
    (C, L, C, L, C, L): 6,    # cereal-legume
    (C, "?", C, F, C, F): 4,  # one unknown year
})


def test_canonical_is_rotation_and_repetition_free():
    assert canonical([F, C]) == canonical([C, F]) == canonical([C, F, C, F]) == (C, F)
    assert canonical([L, C, C]) == canonical([C, L, C]) == (C, C, L)
    assert canonical([C, C, C]) == (C,)
    assert canonical([]) == ()


def test_cyclic_phase_matching_exact():
    n = NearbyUse(HIST, max_mismatch=0)
    assert n.cropland_pixels == 100
    assert n.share(crops(F, C)) == pytest.approx(0.60)  # both phases count
    assert n.share(crops(C, F)) == n.share(crops(F, C, F, C))
    assert n.share(crops(L, C, C)) == pytest.approx(0.25)  # any phase of cereal-cereal-legume
    assert n.share(crops(C, L)) == pytest.approx(0.06)
    assert n.share(crops(O, C)) == 0.0


def test_mismatch_tolerance_and_unknown_years():
    n = NearbyUse(HIST, max_mismatch=1)
    # +5 (one odd year) +4 (unknown year counts as the one mismatch)
    assert n.share(crops(C, F)) == pytest.approx(0.69)
    # cereal-legume: C L C L C L exact; C C L C C L differs in 3 years at best
    assert n.share(crops(C, L)) == pytest.approx(0.06)
    assert NearbyUse(HIST, max_mismatch=2).share(crops(C, L)) == pytest.approx(0.06)
    # with 3 allowed, C C L C C L counts too, but wheat-fallow never does: legume is never seen
    assert NearbyUse(HIST, max_mismatch=3).share(crops(C, L)) == pytest.approx(0.31)


def test_cover_crop_never_matches():
    n = NearbyUse(HIST, max_mismatch=1)
    # A 4-year pattern with one cover-crop year is within one mismatch of C C C F C C in some phase,
    # but the crop map cannot show cover crops, so it never counts.
    assert n.share(crops(C, F, C, "cover_crop")) == 0.0
    assert n.share(crops("cover_crop")) == 0.0
    assert n.share([]) == 0.0


def test_tolerance_never_erases_a_pattern_year():
    n = NearbyUse(payload({(C, F, C, F, C, F): 10, (C, C, L, C, C, C): 5}), max_mismatch=1)
    # Over 6 years a 4-year pattern has slots seen only once; one mismatch must not erase one.
    assert n.share(crops(C, F, C, O)) == 0.0
    assert n.share(crops(C, C, C, F)) == 0.0
    assert n.share(crops(C, C, C, C, C, O)) == 0.0  # oilseed is mapped but never seen
    # A slot seen twice may be wrong once: C C L C C [C] still follows cereal-cereal-legume.
    assert n.share(crops(C, C, L)) == pytest.approx(5 / 15)


def test_results_are_cached_by_pattern():
    n = NearbyUse(HIST, max_mismatch=1)
    calls = []
    orig = n._compute
    n._compute = lambda p: calls.append(p) or orig(p)
    for _ in range(50):
        n.share(crops(C, F))
        n.share(crops(F, C))
        n.share(crops(C, F, C, F))
    assert calls == [(C, F)]


def test_top_patterns():
    n = NearbyUse(HIST, max_mismatch=0)
    top = n.top_patterns(5)
    assert top[0] == {"roles": [C, F], "share": 0.6}
    assert {"roles": [C, C, L], "share": 0.25} in top
    assert all(t["share"] > 0 for t in top)
    assert all(len(t["roles"]) >= 2 for t in n.top_patterns(5, min_len=2))
    d = n.describe()
    assert d["cropland_pixels"] == 100 and d["cropland_ha"] == pytest.approx(9.0)


def test_bad_payload_rejected():
    with pytest.raises(ValueError):
        NearbyUse({"years": [2020, 2021], "sequences": {"cereal": 3}})
    with pytest.raises(ValueError):
        NearbyUse({"years": [], "sequences": {}})


def test_code_roles_from_content():
    content = SimpleNamespace(crops=[
        SimpleNamespace(role=C, codes=lambda s: (24,)),
        SimpleNamespace(role=F, codes=lambda s: (61,)),
        SimpleNamespace(role="cover_crop", codes=lambda s: ()),
    ])
    assert code_roles(content) == {24: C, 61: F}


def test_raster_histogram_aligns_years_of_different_shape(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    from fieldshift.providers.us.cdl_sequences import role_sequence_histogram

    tr = from_origin(-1_700_000, 2_890_000, 30, 30)
    years = {2020: (24, 61), 2021: (61, 24), 2022: (24, 61)}
    paths = {}
    for y, (a, b) in years.items():
        w = 21 if y == 2021 else 20  # one year one column wider, as in the real county files
        arr = np.full((20, w), a, dtype=np.uint8)
        arr[:, 10:] = b
        if y == 2020:
            arr[0, 0] = 176  # grassland that year: unknown
        if y == 2022:
            arr[19, 19] = 0  # outside the map
        p = tmp_path / f"cdl_{y}.tif"
        with rasterio.open(p, "w", driver="GTiff", height=20, width=w, count=1, dtype="uint8",
                           crs="EPSG:5070", transform=tr) as dst:
            dst.write(arr, 1)
        paths[y] = p
    from pyproj import Transformer
    to_ll = Transformer.from_crs(5070, 4326, always_xy=True)
    x0, y0, x1, y1 = -1_700_000, 2_890_000 - 600, -1_700_000 + 600, 2_890_000
    ring = [to_ll.transform(x, y) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
    geom = {"type": "Polygon", "coordinates": [ring]}
    h = role_sequence_histogram(paths, geom, {24: C, 61: F}, max_unknown_years=0)
    assert h["years"] == [2020, 2021, 2022]
    assert h["outside_pixels"] == 1
    assert h["sequences"]["cereal|fallow|cereal"] + h["sequences"]["fallow|cereal|fallow"] == h["cropland_pixels"]
    assert h["cropland_pixels"] + h["non_cropland_pixels"] + h["outside_pixels"] == h["buffer_pixels"]
    assert h["non_cropland_pixels"] == 1
    h1 = role_sequence_histogram(paths, geom, {24: C, 61: F}, max_unknown_years=1)
    assert h1["sequences"].get("?|fallow|cereal") == 1
    n = NearbyUse(h1, max_mismatch=0)
    assert n.share(crops(C, F)) == pytest.approx(1 - 1 / h1["cropland_pixels"])
