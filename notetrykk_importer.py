"""
Notetrykk — Supabase Importer
Reads notetrykk_import.xlsx and inserts into Supabase.

Usage:
    pip install requests openpyxl
    python notetrykk_importer.py

The Excel file must be in the same folder as this script.
Columns (row 1 = header, data from row 2):
    A: Person       — "Last, First" or "A | B" for multiple
    B: Rolle        — Komponist / Arrangør / Utgiver  (| separated for multiple)
    C: Tittel       — title, "/subtitle", "(Lyricist)" extraction automatic
    D: Besetning    — legacy_code, or "code1 | code2" for multiple (first known used)
    E: Forlag       — publisher name
    F: Platenr      — plate number
    G: Utgivelsesår — year, "1880 - 1889", "1905 ca" etc.
    H: Måned        — month string
    I: Periodikum   — "Nordisk Musik-Tidende 1890 h.10" etc.
    J: Kommentar    — notes (stored in composition_notes)
"""

import re
import sys
from pathlib import Path
import requests
import openpyxl

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL = "https://lmsqnyssnxsiibnyguxy.supabase.co"
SUPABASE_KEY = "sb_secret_REDACTED_ROTATE_ME"   # paste your sb_secret_... key here

EXCEL_FILE   = Path(__file__).parent / "notetrykk_import.xlsx"

HEADERS = {
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "apikey":        SUPABASE_KEY,
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

# ── Role mapping ──────────────────────────────────────────────────────────────
ROLE_MAP = {
    "Komponist": "Composer",
    "Arrangør":  "Arranger",
    "Utgiver":   "Editor",
    "Redaktør":  "Editor",
}

# ── Caches (populated at runtime) ─────────────────────────────────────────────
INSTRUMENTATION_CACHE = {}   # legacy_code  → instrumentation_id
PUBLISHER_CACHE       = {}   # name         → publisher_id
PERSON_CACHE          = {}   # "Last, First" → person_id
PERIODICAL_CACHE      = {}   # title        → periodical_id
ISSUE_CACHE           = {}   # (pid, ref)   → issue_id
UNKNOWN_CODES         = set()


# ── Helpers ───────────────────────────────────────────────────────────────────

def api_get(path):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=HEADERS)
    r.raise_for_status()
    return r.json()

def api_post(table, payload, extra_prefer=""):
    prefer = "return=representation"
    if extra_prefer:
        prefer += "," + extra_prefer
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": prefer},
        json=payload,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"POST {table} failed {r.status_code}: {r.text[:300]}")
    return r.json()[0]


def load_instrumentation():
    rows = api_get("instrumentation?select=instrumentation_id,legacy_code")
    for row in rows:
        if row["legacy_code"]:
            INSTRUMENTATION_CACHE[row["legacy_code"]] = row["instrumentation_id"]
    print(f"  Loaded {len(INSTRUMENTATION_CACHE)} instrumentation codes")


def parse_year(raw):
    raw = (raw or "").strip()
    if not raw:
        return None, None, None
    if re.match(r"^\d{4} - \d{4}$", raw):
        parts = raw.split(" - ")
        return parts[0], parts[1], "range"
    if raw.endswith(" ca"):
        return raw[:-3].strip(), None, "circa"
    if raw.endswith("c"):
        return raw[:-1], None, "circa"
    if raw.endswith("f"):
        return raw[:-1], None, "before"
    if re.match(r"^\d{3}\*$", raw):
        return raw[:-1] + "0", None, "decade"
    if re.match(r"^\d{4}$", raw):
        return raw, None, "exact"
    return raw, None, None   # fallback


def parse_title(raw):
    """Returns (title, subtitle, lyricists_list)."""
    raw = (raw or "").strip()
    subtitle = None
    if "/" in raw:
        idx = raw.index("/")
        title_part = raw[:idx].strip()
        subtitle   = raw[idx + 1:].strip()
    else:
        title_part = raw

    lyricists = []
    for text in [title_part, subtitle]:
        if not text:
            continue
        for match in re.findall(r"\(([^)]+)\)", text):
            words = match.strip().split()
            if 1 <= len(words) <= 4 and not any(c.isdigit() for c in match):
                lyricists.append(match.strip())

    return title_part, subtitle, lyricists


def parse_periodikum(raw):
    """Returns (periodical_title, raw_reference) or (None, None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    m = re.match(r"^(.+?)\s+((?:NR |TrR )?(?:h\.)[\w./-]+|\d{4}[\w]*)$", raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Year-only suffix like "1887 ekstrabilag" — no parseable ref
    return raw, None


def get_or_create_publisher(name):
    name = name.strip()
    if not name:
        return None
    if name in PUBLISHER_CACHE:
        return PUBLISHER_CACHE[name]
    row = api_post("publisher", {
        "publisher_name":    name,
        "city":              "Christiania",
        "is_self_published": name.lower() == "eget",
        "is_unknown":        name.lower() == "ukjent",
    }, extra_prefer="resolution=merge-duplicates")
    PUBLISHER_CACHE[name] = row["publisher_id"]
    return row["publisher_id"]


def get_or_create_person(raw_name):
    raw_name = raw_name.strip()
    if not raw_name:
        return None
    if raw_name in PERSON_CACHE:
        return PERSON_CACHE[raw_name]

    if raw_name.lower() == "anon":
        last, first, ptype = "Anon", None, "anon"
    elif "," in raw_name:
        parts  = raw_name.split(",", 1)
        last   = parts[0].strip()
        first  = parts[1].strip() or None
        ptype  = "person"
    else:
        last, first, ptype = raw_name, None, "person"

    payload = {"last_name": last, "person_type": ptype}
    if first:
        payload["first_name"] = first

    row = api_post("person", payload)
    PERSON_CACHE[raw_name] = row["person_id"]
    return row["person_id"]


def get_periodical_id(title):
    if title in PERIODICAL_CACHE:
        return PERIODICAL_CACHE[title]
    rows = api_get(f"periodical?title=eq.{requests.utils.quote(title)}&select=periodical_id")
    if not rows:
        print(f"  WARNING: periodical not found: '{title}'")
        return None
    PERIODICAL_CACHE[title] = rows[0]["periodical_id"]
    return rows[0]["periodical_id"]


def get_or_create_issue(periodical_id, raw_ref):
    key = (periodical_id, raw_ref)
    if key in ISSUE_CACHE:
        return ISSUE_CACHE[key]

    volume = issue_number = series_label = None
    m = re.match(r"^(NR |TrR )?h\.(\d+)$", raw_ref)
    if m:
        series_label = m.group(1).strip() if m.group(1) else None
        digits = m.group(2)
        if len(digits) <= 2:
            issue_number = int(digits)
        else:
            volume       = int(digits[0])
            issue_number = int(digits[1:])

    payload = {"periodical_id": periodical_id, "raw_reference": raw_ref}
    if series_label: payload["series_label"] = series_label
    if volume:       payload["volume"]        = volume
    if issue_number: payload["issue_number"]  = issue_number

    row = api_post("periodical_issue", payload)
    ISSUE_CACHE[key] = row["issue_id"]
    return row["issue_id"]


# ── Excel reader ──────────────────────────────────────────────────────────────

def read_excel(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        # Skip fully empty rows
        if not any(row):
            continue
        def col(i):
            v = row[i] if i < len(row) else None
            return str(v).strip() if v is not None else ""

        persons_raw  = col(0)
        roles_raw    = col(1)
        title_raw    = col(2)
        besetning    = col(3)
        publisher    = col(4)
        plate        = col(5)
        year         = col(6)
        month        = col(7)
        periodikum   = col(8)
        kommentar    = col(9)

        # Multiple persons/roles separated by " | "
        person_names = [p.strip() for p in persons_raw.split("|") if p.strip()]
        role_strings = [r.strip() for r in roles_raw.split("|")   if r.strip()]
        if not role_strings:
            role_strings = ["Komponist"]
        if not person_names:
            continue

        persons = []
        for idx, pname in enumerate(person_names):
            role_str = role_strings[idx] if idx < len(role_strings) else role_strings[-1]
            persons.append((pname, role_str))

        records.append({
            "persons":    persons,
            "title_raw":  title_raw,
            "besetning":  besetning,
            "publisher":  publisher,
            "plate":      plate,
            "year":       year,
            "month":      month or None,
            "periodikum": periodikum,
            "kommentar":  kommentar,
        })
    wb.close()
    return records


# ── Main import ───────────────────────────────────────────────────────────────

def import_records():
    if not EXCEL_FILE.exists():
        print(f"ERROR: Excel file not found: {EXCEL_FILE}")
        sys.exit(1)

    print(f"Reading {EXCEL_FILE.name}...")
    records = read_excel(EXCEL_FILE)
    print(f"  {len(records)} rows to import")

    print("Loading instrumentation codes from Supabase...")
    load_instrumentation()
    print()

    ok = errors = 0

    for rec in records:
        title_raw = rec["title_raw"]
        try:
            # 1. Title / subtitle / lyricists
            title, subtitle, lyricists = parse_title(title_raw)

            # 2. Year
            year_issued, year_issued_end, year_qualifier = parse_year(rec["year"])

            # 3. Instrumentation — use first known code from | separated list
            codes = [c.strip() for c in rec["besetning"].replace("|", " ").split()]
            instrumentation_id = None
            raw_instrumentation = None
            for code in codes:
                if code in INSTRUMENTATION_CACHE:
                    instrumentation_id = INSTRUMENTATION_CACHE[code]
                    break
            if not instrumentation_id and rec["besetning"]:
                raw_instrumentation = rec["besetning"]
                UNKNOWN_CODES.add(rec["besetning"])

            # 4. Publisher
            publisher_id = get_or_create_publisher(rec["publisher"]) if rec["publisher"] else None

            # 5. Composition
            comp = {"title": title}
            if subtitle:             comp["subtitle"]            = subtitle
            if publisher_id:         comp["publisher_id"]        = publisher_id
            if instrumentation_id:   comp["instrumentation_id"]  = instrumentation_id
            if raw_instrumentation:  comp["raw_instrumentation"] = raw_instrumentation
            if rec["plate"]:         comp["plate_number"]        = rec["plate"]
            if year_issued:          comp["year_issued"]         = year_issued
            if year_issued_end:      comp["year_issued_end"]     = year_issued_end
            if year_qualifier:       comp["year_qualifier"]      = year_qualifier
            if rec["month"]:         comp["month"]               = rec["month"]
            if rec["kommentar"]:     comp["composition_notes"]   = rec["kommentar"]

            comp_row = api_post("composition", comp)
            composition_id = comp_row["composition_id"]

            # 6. Persons
            for idx, (pname, role_str) in enumerate(rec["persons"]):
                person_id = get_or_create_person(pname)
                if not person_id:
                    continue
                api_post("composition_person", {
                    "composition_id": composition_id,
                    "person_id":      person_id,
                    "role":           ROLE_MAP.get(role_str, "Composer"),
                    "is_primary":     (idx == 0),
                })

            # 7. Lyricists extracted from title
            for lyr in lyricists:
                person_id = get_or_create_person(lyr)
                if person_id:
                    api_post("composition_person", {
                        "composition_id": composition_id,
                        "person_id":      person_id,
                        "role":           "Lyricist",
                        "is_primary":     False,
                    })

            # 8. Periodikum
            if rec["periodikum"]:
                per_title, raw_ref = parse_periodikum(rec["periodikum"])
                if per_title and raw_ref:
                    per_id = get_periodical_id(per_title)
                    if per_id:
                        issue_id = get_or_create_issue(per_id, raw_ref)
                        if issue_id:
                            api_post("composition_issue", {
                                "composition_id": composition_id,
                                "issue_id":       issue_id,
                            }, extra_prefer="resolution=merge-duplicates")

            ok += 1
            print(f"  OK  [{composition_id:4d}] {title[:65]}")

        except Exception as e:
            print(f"  ERR  '{title_raw[:60]}': {e}")
            errors += 1

    print(f"\n─── Done: {ok} inserted, {errors} errors ───")
    if UNKNOWN_CODES:
        print("\nUnknown instrumentation codes → stored as raw_instrumentation:")
        for c in sorted(UNKNOWN_CODES):
            print(f"  {c!r}")


if __name__ == "__main__":
    import_records()
