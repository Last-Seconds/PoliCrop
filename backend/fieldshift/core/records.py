"""The farmer's harvest records (brief 3, part B): reading a table, units, sanity checks.

A record is one crop year on one field: year, crop, and the harvest as yield per acre or as the total from the
field. Everything here treats input as untrusted: files are read for values only (never formulas, never
macros), every row is checked on its own, and a bad row never blocks the good ones.

Pure: no network, no web framework. The xlsx reader and writer use only the standard library: an .xlsx file
is a zip of XML parts, and only the first worksheet's stored cell values are read.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .content import Content

MAX_FILE_BYTES = 1_000_000
MAX_UNZIPPED_BYTES = 8_000_000
MAX_ROWS = 400
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REASONS = {  # brief 3, part B: answer -> what it does to fitting (the 0.5 is assumed)
    "drought_heat": 1.0, "disease_pests_weeds": 0.0, "hail_frost": 0.0, "management": 0.0, "unknown": 0.5,
}
REASON_WORDS = {"drought_heat": "Drought or heat", "disease_pests_weeds": "Disease, pests or weeds",
                "hail_frost": "Hail or frost", "management": "Late sowing or another change in how it was farmed",
                "unknown": "I don't know"}

# Loose names a farmer might use; crop table names and aliases are matched too.
CROP_WORDS = [
    (r"\b(sww|hrw|winter\s*wheat|w\.?\s*wheat|fall\s*wheat|ww)\b", "winter_wheat"),
    (r"\b(spring\s*wheat|s\.?\s*wheat|hrs|sws|dns|sw)\b", "spring_wheat"),
    (r"\bbarley\b", "spring_barley"),
    (r"\bwinter\s*peas?\b|\baustrian", "winter_peas"),
    (r"\b(peas?|dry\s*peas?|green\s*peas?|yellow\s*peas?)\b", "spring_peas"),
    (r"\blentils?\b", "lentils"),
    (r"\b(chick\s*peas?|garbanzos?)\b", "chickpeas"),
    (r"\bwinter\s*canola\b", "winter_canola"),
    (r"\b(canola|rapeseed)\b", "spring_canola"),
    (r"\bwheat\b", "winter_wheat"),
]
UNIT_WORDS = [
    (r"\b(bu|bushels?)\b", "bu"), (r"\b(cwt|hundredweight)\b", "cwt"), (r"\b(tons?|t)\b", "ton"),
    (r"\b(lbs?|pounds?)\b", "lb"),
]
COLUMN_WORDS = {
    "year": r"(year|yr|season|harvest\s*year|crop\s*year)",
    "crop": r"(crop|commodity|what)",
    "harvest": r"(yield|harvest|amount|production|bu|lbs?|pounds|cwt|tons?)",
    "unit": r"^\s*(unit|units)\s*$",
    "basis": r"(per\s*acre|total|basis)",
}


@dataclass
class ReadRow:
    line: int
    raw: list[str]
    year: int | None = None
    crop: str | None = None
    value: float | None = None
    unit: str | None = None
    basis: str = "per_acre"  # per_acre | total
    yield_lb_ac: float | None = None
    status: str = "ok"  # ok | confirm | error | empty
    reason: str | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("line", "raw", "year", "crop", "value", "unit", "basis",
                                              "yield_lb_ac", "status", "reason")}


@dataclass
class TableRead:
    columns: dict[str, int | None]
    header: list[str]
    unsure: list[str] = field(default_factory=list)
    rows: list[ReadRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"columns": self.columns, "header": self.header, "unsure": self.unsure,
                "rows": [r.to_dict() for r in self.rows]}


# ------------------------------------------------------------------------------------------- files

class FileRefused(ValueError):
    """The whole file is refused (shown to the farmer with this message)."""


def read_file(name: str, data: bytes) -> list[list[str]]:
    """Rows of cell values from a .csv or .xlsx file. Refuses macro-enabled workbooks and oversized files."""
    lower = (name or "").lower()
    if len(data) > MAX_FILE_BYTES:
        raise FileRefused(f"the file is larger than {MAX_FILE_BYTES // 1000} KB; a harvest table is much smaller.")
    if lower.endswith((".xlsm", ".xltm", ".xlsb", ".xls")):
        raise FileRefused("this kind of workbook is not read (macro-enabled or old format). Save it as .xlsx or .csv.")
    if lower.endswith(".xlsx") or data[:2] == b"PK":
        return read_xlsx(data)
    if lower.endswith((".csv", ".txt")) or not lower:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        return read_csv(text)
    raise FileRefused("only .xlsx and .csv files are read.")


def read_csv(text: str) -> list[list[str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)][:MAX_ROWS + 1]


def read_xlsx(data: bytes) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise FileRefused("the workbook could not be opened.") from None
    names = set(z.namelist())
    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
        raise FileRefused("the workbook is too large once unpacked.")
    ctypes = z.read("[Content_Types].xml").decode("utf-8", "replace") if "[Content_Types].xml" in names else ""
    if any("vbaproject" in n.lower() for n in names) or "macroEnabled" in ctypes:
        raise FileRefused("the workbook contains macros. Save it as a plain .xlsx or .csv.")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    sheet = "xl/worksheets/sheet1.xml"
    if sheet not in names:
        sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        if not sheets:
            raise FileRefused("the workbook has no worksheet.")
        sheet = sheets[0]
    root = ET.fromstring(z.read(sheet))
    rows: list[list[str]] = []
    for r in root.iter(f"{{{NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in r.findall("m:c", NS):
            ref = c.get("r") or ""
            col = _col_index(re.sub(r"\d", "", ref)) if ref else len(cells)
            t = c.get("t")
            v = c.find("m:v", NS)  # the stored value only; a formula (<f>) is never evaluated
            if t == "s" and v is not None and v.text is not None:
                k = int(v.text)
                val = shared[k] if 0 <= k < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            else:
                val = v.text if v is not None and v.text is not None else ""
            cells[col] = val.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        if len(rows) > MAX_ROWS:
            break
    return rows


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return max(0, n - 1)


def _col_letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def write_xlsx(rows: list[list]) -> bytes:
    """A minimal workbook (one sheet, inline strings and numbers): the blank sheet the farmer fills in."""
    sheet_rows = []
    for i, row in enumerate(rows, start=1):
        cells = []
        for j, v in enumerate(row):
            ref = f"{_col_letters(j)}{i}"
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif v not in (None, ""):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_esc(v)}</t></is></c>')
        sheet_rows.append(f'<row r="{i}">{"".join(cells)}</row>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Harvests" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()


TEMPLATE_HEADER = ["Year", "Crop", "Harvest", "Unit", "Per acre or total"]


def template_rows(years_crops: list[tuple[int, str, str]]) -> list[list]:
    """The blank sheet: this field's years and crops, one empty harvest column. (year, crop name, unit)."""
    return [TEMPLATE_HEADER] + [[y, name, "", unit, "per acre"] for y, name, unit in years_crops]


# ------------------------------------------------------------------------------------------- reading a table

def match_crop(text: str, content: Content) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    for c in content.offered_crops():
        if t in (c.id, c.name.lower()) or t in (a.lower() for a in c.aliases):
            return c.id
    for pat, cid in CROP_WORDS:
        if re.search(pat, t):
            return cid
    return None


def match_unit(text: str) -> str | None:
    t = (text or "").strip().lower()
    for pat, u in UNIT_WORDS:
        if re.search(pat, t):
            return u
    return None


def guess_columns(header: list[str]) -> tuple[dict[str, int | None], list[str]]:
    cols: dict[str, int | None] = {}
    unsure = []
    used: set[int] = set()
    for key in ("year", "crop", "unit", "basis", "harvest"):
        hits = [i for i, h in enumerate(header) if i not in used and re.search(COLUMN_WORDS[key], (h or "").lower())]
        cols[key] = hits[0] if hits else None
        if len(hits) > 1 and key in ("year", "crop", "harvest"):
            unsure.append(key)
        if hits:
            used.add(hits[0])
    return cols, unsure


def _number(text: str) -> float | None:
    t = (text or "").strip().replace(",", "").replace("$", "")
    m = re.fullmatch(r"-?\d+(\.\d+)?", t)
    return float(t) if m else None


def lb_per_unit(unit: str, crop_id: str, settings) -> float | None:
    """Pounds in one unit of this crop's harvest; None if the unit does not apply to the crop."""
    bushel = settings["records.bushel_lb"]
    if unit == "bu":
        if crop_id in ("winter_wheat", "spring_wheat"):
            return float(bushel["wheat"])
        if crop_id == "spring_barley":
            return float(bushel["barley"])
        return None  # bushels only for wheat and barley (brief 3, part B)
    return {"lb": 1.0, "cwt": 100.0, "ton": 2000.0}.get(unit)


def to_lb_ac(value: float, unit: str, basis: str, crop_id: str, acres: float, settings) -> float | None:
    per = lb_per_unit(unit, crop_id, settings)
    if per is None:
        return None
    lb = value * per
    return lb / acres if basis == "total" else lb


def check_row(row: ReadRow, content: Content, acres: float, typical_lb_ac: dict[str, float]) -> ReadRow:
    s = content.settings
    if row.year is None:
        row.status, row.reason = "error", "no year could be read"
        return row
    if not (1950 <= row.year <= 2100):
        row.status, row.reason = "error", f"{row.year} is not a plausible year"
        return row
    if row.crop is None:
        row.status, row.reason = "error", "the crop was not recognised"
        return row
    c = content.crop(row.crop)
    if c.role in ("fallow", "cover_crop"):
        row.status, row.reason = "error", f"{c.name.lower()} has no harvest"
        return row
    if row.value is None:
        row.status, row.reason = "empty", "no harvest figure"
        return row
    if row.value <= 0:
        row.status, row.reason = "error", "a harvest of zero or less is not used"
        return row
    if row.unit is None:
        row.unit = (c.yield_unit or {}).get("name") or "lb"
        if row.unit == "tons":
            row.unit = "ton"
    if row.basis == "total" and not (acres and acres > 0):
        row.status, row.reason = "error", "a total harvest needs the field's area"
        return row
    v = to_lb_ac(row.value, row.unit, row.basis, row.crop, acres, s)
    if v is None:
        row.status, row.reason = "error", f"{row.unit} is not a unit used for {c.name.lower()}"
        return row
    row.yield_lb_ac = round(v, 1)
    typ = typical_lb_ac.get(row.crop)
    if typ and v > float(s["records.confirm_above_typical"]) * typ:
        row.status = "confirm"
        row.reason = (f"{v:,.0f} lb/acre is more than {s['records.confirm_above_typical']:g} times the typical "
                      f"{typ:,.0f}: check the unit, and confirm to keep it")
    return row


def read_table(rows: list[list[str]], content: Content, acres: float, typical_lb_ac: dict[str, float],
               columns: dict[str, int | None] | None = None) -> TableRead:
    """Rows of cells -> one ReadRow per data row, with how each was read and why any was not."""
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return TableRead(columns={}, header=[])
    header = [str(h) for h in rows[0]]
    has_header = any(re.search(COLUMN_WORDS["year"], h.lower()) or re.search(COLUMN_WORDS["crop"], h.lower())
                     for h in header)
    if columns is None:
        if has_header:
            columns, unsure = guess_columns(header)
        else:  # no header: year, crop, harvest in that order
            columns, unsure = {"year": 0, "crop": 1, "harvest": 2, "unit": 3 if len(header) > 3 else None, "basis": None}, ["header"]
    else:
        unsure = []
    data = rows[1:] if has_header else rows
    out = TableRead(columns=columns, header=header if has_header else [], unsure=unsure)
    head_unit = None
    if columns.get("harvest") is not None and has_header:
        head_unit = match_unit(header[columns["harvest"]])
    head_total = has_header and columns.get("harvest") is not None and "total" in header[columns["harvest"]].lower()

    def cell(r, key):
        i = columns.get(key)
        return r[i] if i is not None and i < len(r) else ""

    for k, r in enumerate(data[:MAX_ROWS], start=2 if has_header else 1):
        row = ReadRow(line=k, raw=[str(x) for x in r])
        ytxt = cell(r, "year")
        y = _number(ytxt)
        row.year = int(y) if y is not None and float(y).is_integer() else None
        row.crop = match_crop(cell(r, "crop"), content)
        htxt = cell(r, "harvest")
        row.value = _number(htxt)
        row.unit = match_unit(cell(r, "unit")) or match_unit(htxt) or head_unit
        btxt = cell(r, "basis").lower()
        row.basis = "total" if ("total" in btxt or (not btxt and head_total)) else "per_acre"
        out.rows.append(check_row(row, content, acres, typical_lb_ac))
    return out


# ------------------------------------------------------------------------------------------- stored records

@dataclass
class Record:
    year: int
    crop: str
    yield_lb_ac: float
    reason: str | None = None  # the farmer's answer about an odd year, if any


def parse_records(raw, answers, content: Content) -> tuple[list[Record], list[str]]:
    """Records as the browser keeps them -> Records; malformed entries are dropped with a note."""
    out, ignored = [], []
    answers = answers if isinstance(answers, dict) else {}
    if not isinstance(raw, list):
        return out, (["records"] if raw else [])
    seen = set()
    for r in raw[:MAX_ROWS]:
        try:
            year, crop, v = int(r["year"]), str(r["crop"]), float(r["yield_lb_ac"])
        except (KeyError, TypeError, ValueError):
            ignored.append("record")
            continue
        if not content.has_crop(crop) or v <= 0 or not (1950 <= year <= 2100) or v > 50000:
            ignored.append(f"record:{year}")
            continue
        crop = content.crop(crop).id
        if (year, crop) in seen:
            ignored.append(f"record:{year}:duplicate")
            continue
        seen.add((year, crop))
        ans = answers.get(f"{year}:{crop}")
        out.append(Record(year, crop, v, ans if ans in REASONS else None))
    return out, ignored
