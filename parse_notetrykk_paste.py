#!/usr/bin/env python3
"""
Parse pasted Notetrykk/web-page rows into a tab-delimited plain-text file.

Usage:
    python parse_notetrykk_paste_v7_preserve_text.py input.txt output.txt --expect 259
    python parse_notetrykk_paste_v7_preserve_text.py input.txt output.txt --report

The input may be copied directly from a web page/table where visual wrapping has
inserted newlines inside one logical record. The parser reconstructs the 10
logical columns:

    Person, Rolle, Tittel, Besetning, Forlag, Platenr,
    Utgivelsesår, Måned, Periodikum, Kommentar

Important supported cases:
- wrapped Besetning values, e.g. p2\nvn, blkor\ns-git, 2st\n3st
- wrapped/multiple Rolle values, e.g. Komponist\nArrangør
- pipe-separated people/roles, e.g. Fremstad,O | Ring, F / Utgiver | Komponist
- missing plate numbers
- year ranges and approximate years, e.g. 1890 - 1899, 1890 ca
- plate ranges, e.g. 1716-20
- four-digit plate numbers followed by a publication year/month; titles containing publisher words
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

HEADERS = [
    "Person", "Rolle", "Tittel", "Besetning", "Forlag",
    "Platenr", "Utgivelsesår", "Måned", "Periodikum", "Kommentar",
]

ROLES = ("Komponist", "Utgiver", "Arrangør")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Des")

# Keep longer publisher names before shorter ones. Add new publishers here when found.
PUBLISHERS = sorted({
    "Den rel. Traktatfor.",
    "Tromsø Musikh. Forlag",
    "Brødrene Cloetta",
    "Christiansen Herman",
    "Luthetstiftelsen",   # typo seen in one source
    "Lutherstiftelsen",
    "Aktietrykkeriet",
    "De 1000 Hjem",
    "Folkebladet",
    "Aschehoug",
    "Cappelen",
    "Fabritius",
    "Harloff",
    "Malling",
    "Røsholm",
    "Warmuth",
    "Zapffe",
    "Tvedte L E",
    "Huseby & Co",
    "Hauff",
    "Hals",
    "Rabe",
    "Bøgh",
    "Eget",
    "Wolff F Chr",
    "Nyt Tidsskrift",
    "Giertsen",
    "ukjent",
    "Winther E",
    "Lindorff",
    "Neupert",
    "Behrens",
    "Olsen",
    "Cammermeyer",
    "Brækstad",
    "Hanche",
    "Jensen H J",
}, key=len, reverse=True)

# Known Besetning / instrumentation values. Right-edge matching against this
# list is what makes wrapped fields parse correctly.
INSTRUMENTATION_PHRASES = sorted({
    "2st", "2st 3st", "3st", "2s-p",
    "blkor", "blkor harm", "blkor s-git", "blkor mkor",
    "dkor-org", "dkor-p2",
    "fl-p", "fl-p vn-p",
    "harm", "harm p2", "litur",
    "klaveruttog",
    "korps",
    "messingkvint", "messingsekst",
    "mkor", "mkor-blkor", "mkor-ork",
    "org", "ork", "ork-p4",
    "p2", "p2 s-p", "p2 vn", "p4",
    "sangbok",
    "s-git", "s-git sangbok",
    "s-ork", "s-p", "s-ork",
    "skole", "skole althorn", "skole b-kornett", "skole basun",
    "skole ess-kornett", "skole ess-tuba", "skole git", "skole p",
    "skole s", "skole tuba",
    "skolesangbok",
    "solo-blkor-p2", "solo-kor-p2", "solo-mkor",
    "soli-kor-ork", "soli-mkor-p2",
    "vc-p", "vn", "vn-p",
}, key=lambda x: (len(x.split()), len(x)), reverse=True)

ROLE_RE = re.compile(r"\b(" + "|".join(map(re.escape, ROLES)) + r")\b")
YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2})(?:\s*(?:-|–)\s*(18\d{2}|19\d{2}))?(?:\s*ca)?\b")
MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\b")
NMT_RE = re.compile(r"Nordisk Musik-Tidende\s+\d{4}\s+h\.\d{2}")


@dataclass
class ParseWarning:
    record_no: int
    message: str
    row: Optional[List[str]] = None


def clean_cell(s: str) -> str:
    """Normalize whitespace only; do not change spelling or words."""
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


def normalize_raw_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Convert spaces around real tabs to one tab, but keep ordinary spaces.
    text = re.sub(r"[ \u00a0]*\t[ \u00a0]*", "\t", text)
    return text


def looks_like_record_start(line: str) -> bool:
    """
    A new record starts where a plausible Person field is followed by a role.
    Continuation lines such as just 'Arrangør' or 'p2' do not qualify.
    """
    line = line.strip()
    if not line or line.startswith("Person\tRolle\t"):
        return False
    m = ROLE_RE.search(line)
    if not m:
        return False
    before = line[:m.start()].strip(" \t")
    if not before or before[0].isdigit():
        return False
    # A continuation line whose entire prefix is punctuation is not a person.
    if not re.search(r"[A-Za-zÆØÅæøåÄÖÜäöüÉé]", before):
        return False
    return True


def split_records(text: str) -> List[str]:
    """Split raw pasted text into logical records, retaining wrapped lines."""
    records: List[List[str]] = []
    current: List[str] = []

    for raw_line in normalize_raw_text(text).split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                current.append(" ")
            continue
        if line.startswith("Person\tRolle\t") or clean_cell(line) == " ".join(HEADERS):
            continue
        if looks_like_record_start(line):
            if current:
                records.append(current)
            current = [line]
        elif current:
            current.append(line)
        # Else ignore leading noise.

    if current:
        records.append(current)

    return ["\t".join(part for part in rec) for rec in records]


def find_publisher_hits(text: str) -> List[Tuple[int, str]]:
    """Return all known publisher-token matches in text.

    A title may itself contain a publisher word, e.g. "Das Hals Album".
    Therefore the parser must not simply take the first publisher-looking
    token. We collect all matches and let parse_record choose the rightmost
    match whose following publication tail parses cleanly.
    """
    hits: List[Tuple[int, str]] = []
    occupied: List[Tuple[int, int]] = []

    # Longer names are tried first so "Tromsø Musikh. Forlag" wins over
    # any shorter substring that might later be added.
    for pub in PUBLISHERS:
        for m in re.finditer(r"(?<!\S)" + re.escape(pub) + r"(?!\S)", text):
            span = (m.start(), m.end())
            if any(not (span[1] <= a or span[0] >= b) for a, b in occupied):
                continue
            hits.append((m.start(), pub))
            occupied.append(span)

    return sorted(hits, key=lambda x: (x[0], len(x[1])))


def consume_role_segment(text: str) -> Tuple[str, str]:
    """
    Split 'Person Role [Role...] Title...' into (role, rest_after_roles).

    Handles:
        Komponist <title>
        Komponist Arrangør <title>
        Komponist\tArrangør\t<title>
        Utgiver | Komponist <title>
    """
    text = clean_cell(text)
    roles: List[str] = []
    rest = text

    # First role must be at the start of this segment.
    while True:
        rest = clean_cell(rest)
        # Drop a leading pipe separator left from 'Utgiver | Komponist'.
        if rest.startswith("|"):
            rest = clean_cell(rest[1:])
        matched = False
        for r in ROLES:
            if rest == r:
                roles.append(r)
                rest = ""
                matched = True
                break
            if rest.startswith(r + " "):
                roles.append(r)
                rest = clean_cell(rest[len(r):])
                matched = True
                break
        if not matched:
            break

    # Preserve pipe style when it was explicit in the role segment, otherwise use a space.
    role = " | ".join(roles) if "|" in text[:80] else " ".join(roles)
    return role, rest


def split_title_besetning(before_pub: str) -> Tuple[str, str]:
    """Split text before publisher into Title and Besetning.

    The pasted web table sometimes wraps instrumentation onto one or more
    continuation lines, and after whitespace normalization that can look like::

        Gravsalme: Bedre kan jeg ikke fare blkor mkor Warmuth ...

    Earlier versions only recognized a fixed phrase list, so the first wrapped
    token (``blkor``) could remain attached to the title while ``mkor`` became
    Besetning. This function first tries the curated phrase list, then falls
    back to a right-edge scan over atomic instrumentation tokens so combinations
    such as ``blkor mkor`` are captured as one Besetning field.
    """
    before_pub = clean_cell(before_pub)

    # 1) Exact/curated multi-token phrases first. Longest phrases are first.
    for phrase in INSTRUMENTATION_PHRASES:
        if before_pub == phrase:
            return "", phrase
        suffix = " " + phrase
        if before_pub.endswith(suffix):
            return clean_cell(before_pub[:-len(suffix)]), phrase

    # 2) Generalized wrapped-instrumentation fallback. Consume consecutive
    # atomic instrumentation tokens from the right edge. This handles new
    # combinations without having to enumerate every pair in advance.
    atomic_instr = {
        token
        for phrase in INSTRUMENTATION_PHRASES
        for token in phrase.split()
        if token not in {"-", "–"}
    }

    tokens = before_pub.split()
    if len(tokens) >= 2:
        cut = len(tokens)
        while cut > 0 and tokens[cut - 1] in atomic_instr:
            cut -= 1
        # Require at least one title token before the instrumentation tokens.
        # Also require at least one consumed token; otherwise no match.
        if 0 < cut < len(tokens):
            title = " ".join(tokens[:cut])
            besetning = " ".join(tokens[cut:])
            return clean_cell(title), clean_cell(besetning)

    # Conservative fallback: final token is probably Besetning, but reportable.
    parts = before_pub.rsplit(" ", 1)
    if len(parts) == 2:
        return clean_cell(parts[0]), clean_cell(parts[1])
    return before_pub, ""



def is_plate_token(tok: str) -> bool:
    """Return True for simple plate-number tokens such as 5, 1536, 1716-20."""
    return bool(re.fullmatch(r"\d{1,5}(?:-\d{1,5})?", tok))


def is_year_token(tok: str) -> bool:
    return bool(re.fullmatch(r"18\d{2}|19\d{2}", tok))


def parse_year_at(tokens: List[str], i: int) -> Optional[Tuple[str, int]]:
    """Parse a year/range/ca expression beginning at tokens[i]."""
    if i >= len(tokens) or not is_year_token(tokens[i]):
        return None
    year_parts = [tokens[i]]
    j = i + 1
    if j + 1 < len(tokens) and tokens[j] in {"-", "–"} and is_year_token(tokens[j + 1]):
        year_parts.extend(["-", tokens[j + 1]])
        j += 2
    elif j < len(tokens) and re.fullmatch(r"[-–](18\d{2}|19\d{2})", tokens[j]):
        year_parts.append("- " + tokens[j].lstrip("-–"))
        j += 1
    if j < len(tokens) and tokens[j] == "ca":
        year_parts.append("ca")
        j += 1
    return clean_cell(" ".join(year_parts)), j


def tail_starts_like_expected_remainder(tokens: List[str], start: int) -> bool:
    """After the publication year we normally see month, periodical, comment, or nothing."""
    if start >= len(tokens):
        return True
    if tokens[start] in MONTHS:
        return True
    if tokens[start:start + 2] == ["Nordisk", "Musik-Tidende"]:
        return True
    # Keep comments possible, but a bare plate-looking number directly after the chosen
    # year is a strong sign that we chose the wrong year among several numeric tokens.
    if is_plate_token(tokens[start]) or is_year_token(tokens[start]):
        return False
    return True


def parse_publication_tail(after_pub: str) -> Tuple[str, str, str]:
    """
    Split text after publisher into (plate, year, tail_after_year).

    Important refinement: if a publisher is followed by a plate number that is
    itself a four-digit number, then another four-digit publication year, e.g.

        Warmuth 1889 1891 Feb Nordisk Musik-Tidende ...
        Warmuth 1891 1891 Jul Nordisk Musik-Tidende ...
        Warmuth 1673 1674 1675 1890 Okt

    the first numeric token(s) are Platenr and the final suitable year token is
    Utgivelsesår. A simple "first year wins" rule parses these rows wrongly.
    """
    after_pub = clean_cell(after_pub)
    tokens = after_pub.split()
    if not tokens:
        raise ValueError("No publication tail after publisher")

    candidates: List[Tuple[int, str, int, bool]] = []
    for i in range(len(tokens)):
        parsed = parse_year_at(tokens, i)
        if not parsed:
            continue
        year, next_i = parsed
        prefix = tokens[:i]
        if prefix and not all(is_plate_token(t) for t in prefix):
            continue
        good_remainder = tail_starts_like_expected_remainder(tokens, next_i)
        candidates.append((i, year, next_i, good_remainder))

    if not candidates:
        raise ValueError(f"No year found after publisher: {after_pub!r}")

    # Prefer a candidate that leaves a normal-looking month/periodical/comment tail.
    good = [c for c in candidates if c[3]]
    pool = good if good else candidates

    # If there are plate-number tokens before the publication year, choose the
    # rightmost suitable year. This fixes 1889 1891 Feb and 1673 1674 1675 1890 Okt.
    chosen = max(pool, key=lambda c: c[0])
    i, year, next_i, _ = chosen
    plate = clean_cell(" ".join(tokens[:i]))
    tail = clean_cell(" ".join(tokens[next_i:]))
    return plate, year, tail

def parse_record(record: str) -> List[str]:
    """Parse one logical record into exactly 10 fields."""
    # Insert spaces around tabs before whitespace normalization so wrapped cells join naturally.
    protected = record.replace("\t", " \t ")
    parts = [clean_cell(p) for p in re.split(r"\s*\t\s*", protected) if clean_cell(p)]
    joined = clean_cell(" ".join(parts))

    m_role = ROLE_RE.search(joined)
    if not m_role:
        raise ValueError(f"No role token found: {record[:160]}")

    person = clean_cell(joined[:m_role.start()])
    role, rest = consume_role_segment(joined[m_role.start():])
    if not role:
        raise ValueError(f"Could not parse role after person {person!r}: {record[:160]}")

    pub_hits = find_publisher_hits(rest)
    if not pub_hits:
        raise ValueError(f"No known publisher found after {person}: {rest[:180]}")

    chosen = None
    errors = []
    # Prefer the rightmost publisher-looking token whose tail parses.
    # This fixes titles such as "Das Hals Album", where the first "Hals"
    # is part of the title and the second "Hals" is the publisher.
    for pub_pos, publisher in sorted(pub_hits, key=lambda x: x[0], reverse=True):
        before_pub_try = clean_cell(rest[:pub_pos])
        after_pub_try = clean_cell(rest[pub_pos + len(publisher):])
        try:
            plate_try, year_try, tail_try = parse_publication_tail(after_pub_try)
        except Exception as e:
            errors.append(f"{publisher}@{pub_pos}: {e}")
            continue
        title_try, besetning_try = split_title_besetning(before_pub_try)
        chosen = (publisher, title_try, besetning_try, plate_try, year_try, tail_try)
        break

    if chosen is None:
        raise ValueError(
            f"No publisher match had a parseable publication tail after {person}: "
            + "; ".join(errors)
        )

    publisher, title, besetning, plate, year, tail = chosen

    month = ""
    periodical = ""
    comment = ""
    m_month = MONTH_RE.match(tail)
    if m_month:
        month = m_month.group(1)
        tail = clean_cell(tail[m_month.end():])

    nmt = NMT_RE.search(tail)
    if nmt:
        periodical = clean_cell(nmt.group(0))
        comment = clean_cell((tail[:nmt.start()] + " " + tail[nmt.end():]).strip())
    else:
        comment = tail

    return [person, role, title, besetning, publisher, plate, year, month, periodical, comment]


def parse_text(text: str) -> Tuple[List[List[str]], List[ParseWarning]]:
    rows: List[List[str]] = []
    warnings: List[ParseWarning] = []
    records = split_records(text)

    for i, rec in enumerate(records, start=1):
        try:
            row = parse_record(rec)
        except Exception as e:
            raise ValueError(f"Record {i} failed: {e}\nRAW: {rec}") from e
        rows.append(row)

        if len(row) != len(HEADERS):
            warnings.append(ParseWarning(i, f"Bad column count {len(row)}", row))
        if row[3] and row[3] not in INSTRUMENTATION_PHRASES:
            warnings.append(ParseWarning(i, f"Besetning not in known list: {row[3]!r}", row))
        if row[5] and not re.fullmatch(r"[0-9]+(?:[ -][0-9]+)*(?:-[0-9]+)?", row[5]):
            warnings.append(ParseWarning(i, f"Unusual plate number: {row[5]!r}", row))

    return rows, warnings


def parse_file(input_path: Path) -> Tuple[List[List[str]], List[ParseWarning]]:
    return parse_text(input_path.read_text(encoding="utf-8-sig"))


def write_tsv(rows: Iterable[Sequence[str]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(HEADERS) + "\n")
        for row in rows:
            if len(row) != len(HEADERS):
                raise ValueError(f"Bad column count {len(row)}: {row}")
            f.write("\t".join(clean_cell(str(cell)) for cell in row) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse pasted Notetrykk records into tab-delimited plain text.")
    ap.add_argument("input", type=Path, help="Raw pasted input text")
    ap.add_argument("output", type=Path, help="Output .txt file")
    ap.add_argument("--expect", type=int, default=None, help="Expected number of data records; fail if different")
    ap.add_argument("--report", action="store_true", help="Print warnings about unusual parsed fields")
    args = ap.parse_args()

    rows, warnings = parse_file(args.input)
    if args.expect is not None and len(rows) != args.expect:
        raise SystemExit(f"Expected {args.expect} records, parsed {len(rows)} records")
    write_tsv(rows, args.output)

    print(f"Wrote {len(rows)} records to {args.output}")
    if args.report and warnings:
        print(f"\nWarnings ({len(warnings)}):", file=sys.stderr)
        for w in warnings:
            print(f"- record {w.record_no}: {w.message}", file=sys.stderr)
            if w.row:
                print("  " + " | ".join(w.row), file=sys.stderr)


if __name__ == "__main__":
    main()
