# Notetrykk — Claude Code Context

## Project Overview

Norwegian historical music catalogue database. Sheet music metadata from Norwegian/Nordic publishers,
primarily 1811–1908. Source data from University of Oslo (hf.uio.no).
Separate from the live music scores project (Supabase project: tfqnzszyjsdgdeksizel).

**Current status**: Stage 1 import complete (6,922 rows in source_import). Stage 2 in progress —
authority tables populated, publication import pending.

## File Locations

- **Stager script**: `notetrykk_stager.py` — stages raw UiO data into source_import
- **Person extract**: `notetrykk_persons_extract.py` — extracts persons from source_import
- **Person import**: `notetrykk_persons_import.py` — imports corrected persons from Excel
- **Person review**: `persons_review.xlsx` — tier 3 persons needing manual correction
- **Flags file**: `stage2_flags.txt` — running log of unknowns across all batches
- **Supabase URL**: `https://lmsqnyssnxsiibnyguxy.supabase.co`
- **Frontend publishable key**: `sb_publishable_w0SDuDAzg3L0EmtQe4QHDg_T-bW_ADO`
- **Secret key for imports**: stored in `notetrykk_importer.py` — do not overwrite

-----

## Stage 1 Workflow: Stager Script

The stager (`notetrykk_stager.py`) inserts raw UiO tab-separated data into `source_import`.

```bash
py notetrykk_stager.py new_rows.txt
```

**Key behaviour:**
- Inserts `None` (NULL) for empty fields — never empty strings
- Deduplicates via unique constraint on all 10 content fields
- Report written to `stager_report.txt`
- Stage 1 is complete — stager only needed if source data corrections arise

-----

## source_import Column Names

The raw staging table uses these column names (renamed from original Norwegian during schema migration):

| DB column             | Original source field |
|-----------------------|-----------------------|
| source_id             | (auto)                |
| pasted_at             | (auto)                |
| person_raw            | Person                |
| role_raw              | Rolle                 |
| title_raw             | Tittel                |
| instrumentation_raw   | Besetning             |
| publisher_raw         | Forlag                |
| plate_number_raw      | Platenr               |
| publication_year_raw  | Utgivelsesår          |
| month_raw             | Måned                 |
| periodical_raw        | Periodikum            |
| comment_raw           | Kommentar             |
| legacy_composition_id | (old stamp, unused)   |

-----

## Database Schema

### source_import
Raw preservation layer — never destructively edited.
All 10 content fields + source_id + pasted_at + legacy_composition_id.

### role
- role_id (PK), role_name (unique), role_group (work|publication|source|other), notes
- Seeded: Komponist, Tekstforfatter, Arrangør, Bearbeider, Utgiver, Redaktør, Oversetter, Anonym, Ukjent

### role_alias
- role_alias_id (PK), role_id (FK), raw_role, notes

### person
- person_id (PK), last_name, first_name (nullable), display_name,
  sort_name (nullable), person_type ('person'|'anon'|'collection'),
  birth_year (nullable), death_year (nullable), notes (nullable),
  is_edited (bool), corrections (JSONB), corrected_at, corrected_by, created_at

### person_alias
- person_alias_id (PK), person_id (FK), raw_name, alias_type, confidence, source_id (FK), notes

### publisher
- publisher_id (PK), publisher_name (unique), city (default 'Christiania'),
  country, publisher_type, active_from_year, active_to_year,
  is_self_published (bool), is_unknown (bool), notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### publisher_alias
- publisher_alias_id (PK), publisher_id (FK), raw_name, confidence, source_id (FK), notes

### instrumentation
- instrumentation_id (PK), legacy_code (unique), description_no, description_en,
  category ('solo'|'choir'|'ensemble'|'school'), is_school_book (bool), notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### instrumentation_alias
- instrumentation_alias_id (PK), instrumentation_id (FK), raw_value, confidence, source_id (FK), notes

### periodical
- periodical_id (PK), title (unique), abbreviation, ref_format, notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### periodical_alias
- periodical_alias_id (PK), periodical_id (FK), raw_title, confidence, source_id (FK), notes

### periodical_issue
- issue_id (PK), periodical_id (FK), raw_reference, issue_year, issue_month,
  issue_number, series_label, notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### publication  ← main entity (replaces old 'composition' table)
- publication_id (PK), primary_source_id (FK → source_import),
  title, subtitle, plate_number, plate_conflict_note,
  publisher_id (FK), year_issued, year_issued_end,
  year_qualifier ('exact'|'circa'|'before'|'decade'|'range'),
  month, publication_type, periodical_issue_id (FK), composition_notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at, updated_at

### publication_person
- publication_person_id (PK), publication_id (FK), person_id (FK), role_id (FK),
  credited_as, sequence_no, source_id (FK), is_primary (bool), notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### publication_instrumentation
- publication_instrumentation_id (PK), publication_id (FK), instrumentation_id (FK),
  raw_instrumentation, sequence_no, source_id (FK), notes,
  is_edited, corrections (JSONB), corrected_at, corrected_by, created_at

### publication_issue
- publication_issue_id (PK), publication_id (FK), issue_id (FK),
  plate_number_in_issue, notes, created_at

### former_publisher
- former_publisher_id (PK), publication_id (FK), publisher_id (FK),
  raw_former_publisher, evidence_text, sequence_no, source_id (FK), notes, created_at

-----

## Traceability / Edit Audit

Every main table (publication, person, publisher, instrumentation, periodical, periodical_issue,
publication_person, publication_instrumentation) has:
- `is_edited` boolean — set TRUE when any field is manually corrected
- `corrections` JSONB — field-level before/after record, e.g.:
  `{"plate_number": {"original": "2232", "corrected": "2322", "corrected_at": "2026-06-12", "corrected_by": "EI"}}`
- `corrected_at` timestamptz
- `corrected_by` text

The raw source is always preserved in `source_import` and linked via `publication.primary_source_id`.

-----

## Person Name Rules

- Format: `Last, First` → `last_name`, `first_name`
- `Anon` → `person_type = 'anon'`, `last_name = 'Anon'`
- `Anon (C A T)` / `Anon (En Dilettant)` etc. → whole string as `last_name`, `person_type = 'anon'`
- `NN` → `person_type = 'collection'`
- Single name only → `last_name` only, `person_type = 'person'`
- Multiple persons in source: `A & B` → `A | B` in person_raw
- Honorifics (e.g. `Abbed`) in first_name — preserve as-is, do not strip

### Known pseudonyms

| Pseudonym | Real name |
|-----------|-----------|
| Aletter, Wilhelm | Alphonse Tellier |
| Bachmann, G | Fr. Behr |
| Bolt, Finn | Sigurd Lie |
| Bonheur, Theo | Thomas Bulch |
| Brown, Elisa | L. Solberg |
| Clarelius | Alfred Paulsen |
| d'Avout, Fanny | Fanny Egeberg |
| Grahl C G | G C W Prahl |
| Ika | Albertina Fredrika Peyron |
| Lago, N | Laura Netzel |
| Lambert, Leon | Alfred Paulsen |
| Morley, Ch | Fr Behr |
| Nesrednah | H Andersen |
| Petroe, Emil | Emil Petersen |
| Pomposi, Ernesto | Christian Teilman |
| Wilhelmine | Wilhelmine Sørlie |

-----

## Year Parsing Rules

| Source format | year_issued | year_issued_end | year_qualifier |
|---------------|-------------|-----------------|----------------|
| `1852` | 1852 | — | exact |
| `1852c` | 1852 | — | circa |
| `1905 ca` | 1905 | — | circa |
| `1852f` | 1852 | — | before |
| `185*` | 1850 | — | decade |
| `1860 - 1869` | 1860 | 1869 | range |

-----

## Title Parsing Rules

- Split on first `/` → `title` + `subtitle`
- Extract `(Initial Surname)` from title/subtitle → `publication_person` with role Tekstforfatter
  - Heuristic: 1–4 words, no digits, looks like a name
  - Well-known names (Ibsen, Bjørnson, Wergeland) may appear without initials
- Do NOT extract initials from `Anon (C A T)` — that's a person name pattern
- Dedications in titles are NOT lyricists

-----

## Instrumentation Codes

### Known codes (subset — full list in database)

| legacy_code | description_no | category |
|-------------|----------------|----------|
| p2 | tohendig piano | solo |
| p4 | firhendig piano | solo |
| s-p | sang og piano | ensemble |
| vn-p | fiolin og piano | ensemble |
| mkor | mannskor | choir |
| blkor | blandet kor | choir |
| ork | orkester | ensemble |
| s-git | sang og gitar | ensemble |
| korps | korps / messingensemble | ensemble |
| hardingfele | hardingfele | solo |

Full list: 91 codes in the `instrumentation` table.

### Source code aliases

| Source code | Maps to |
|-------------|---------|
| 2 vn | 2vn |
| s-salmodikon | s-salm |
| s-2 fl | s-2fl |
| fl vn | fl-vn |
| harm p2 | harm-p2 |
| 6 horn | 6-horn |
| skole s | skole-s |
| skole kor | skole-kor |
| skole vn | skole-vn |

Full alias list in `instrumentation_alias` table.

### Publication type codes (NOT instrumentation)

| Source code | publication_type value |
|-------------|------------------------|
| sangbok | sangbok |
| skolesangbok | skolesangbok |
| koralbok | koralbok |
| litur | liturgisk |
| skole | skole |
| klaveruttog | klaveruttog |

-----

## Known Periodicals

| Title | Abbreviation | Ref format |
|-------|-------------|------------|
| Den norske Lyra | DNL | 4-digit YYMM |
| Lyra | — | h.XYZ |
| Musikalsk Album | MA | h.XYZ; NR/TrR variants |
| Musikalsk Løverdags-Magazin | MLM | h.XXYY |
| Musikalsk Nyhedsblad | MN | h.XYZ |
| Nordisk Musik-Tidende | NMT | Title YYYY h.NN |
| Nyt Musikalsk Museum | NMM | h.XYZ |
| Amphion | — | Amphion årg.X nr.YY |
| Musik-Magazin for Violin | — | h.X |
| Bragi | — | h.XNN (series+issue) |
| Apollo | — | h.NN |
| Terpsichore | — | h.NN |
| Vinter-Salonen | — | Vinter-Salonen YYYY h.N |
| Danse-Salonen | — | h.NN |
| + 5 more in periodical table | | |

-----

## Known Publishers

119 publishers in the `publisher` table. City defaults to Christiania.

Key publishers: Cappelen, Warmuth, Hals, Huseby & Co, Roverud, Winther, Prahl, Fehr,
Winther E, Guldberg & Dz, Zapffe, Cammermeyer, Aschehoug, Kaland, By.

Special values:
- `Eget` → `is_self_published = TRUE`
- `ukjent` → `is_unknown = TRUE`
- `Winther E` — separate from `Winther` until confirmed

-----

## SQL Patterns

### Add new instrumentation code
```sql
INSERT INTO public.instrumentation (legacy_code, description_no, description_en, category, is_school_book)
VALUES ('code', 'norsk beskrivelse', 'english description', 'ensemble', FALSE);
```

### Add new publisher
```sql
INSERT INTO public.publisher (publisher_name, city, publisher_type, is_self_published, is_unknown, notes)
VALUES ('Name', 'Christiania', 'publisher', FALSE, FALSE, 'notes');
```

### Add new periodical
```sql
INSERT INTO public.periodical (title, abbreviation, ref_format, notes)
VALUES ('Title', 'ABB', 'ref format', NULL);
```

### Record a correction (traceability)
```sql
UPDATE public.publication
SET plate_number  = '2322',
    is_edited     = TRUE,
    corrected_at  = now(),
    corrected_by  = 'EI',
    corrections   = jsonb_set(
        coalesce(corrections, '{}'::jsonb),
        '{plate_number}',
        '{"original": "2232", "corrected": "2322"}'::jsonb
    )
WHERE publication_id = 123;
```

### Check for duplicate publications
```sql
SELECT title, publisher_id, plate_number, year_issued, COUNT(*) as cnt
FROM public.publication
GROUP BY title, publisher_id, plate_number, year_issued
HAVING COUNT(*) > 1;
```

### Check all publications for a person
```sql
SELECT p.publication_id, p.title, p.year_issued, p.plate_number,
       pub.publisher_name, r.role_name
FROM public.publication p
JOIN public.publication_person pp ON pp.publication_id = p.publication_id
JOIN public.person pe ON pe.person_id = pp.person_id
JOIN public.role r ON r.role_id = pp.role_id
LEFT JOIN public.publisher pub ON pub.publisher_id = p.publisher_id
WHERE pe.last_name = 'LastName'
ORDER BY p.year_issued, p.title;
```

### Grants for new tables
```sql
GRANT SELECT ON public.table_name TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role;
```

-----

## Frontend Credentials

```js
const SUPABASE_URL = 'https://lmsqnyssnxsiibnyguxy.supabase.co';
const SUPABASE_KEY = 'sb_publishable_w0SDuDAzg3L0EmtQe4QHDg_T-bW_ADO';
```

Use these in every new HTML page. Never use the secret key in frontend code.

-----

## Field Name Alignment with Live Music Database

Fields intentionally aligned to `public` schema in live Supabase project (tfqnzszyjsdgdeksizel):

| This database | Live database | Table |
|---------------|---------------|-------|
| last_name | last_name | person |
| first_name | first_name | person |
| title | title | publication |
| composition_notes | composition_notes | publication |
| publisher_name | publisher_name | publisher |
| publication_id | composition_id | publication_person |
| person_id | person_id | publication_person |
| role_id → role_name | role | publication_person |
| credited_as | credited_as | publication_person |

-----

## Important Notes

- **Reads**: Claude Code can query Supabase directly via the REST API (PostgREST) using the
  frontend publishable key over HTTPS, e.g.:
  `curl "https://lmsqnyssnxsiibnyguxy.supabase.co/rest/v1/person?last_name=eq.Cappelen&select=*" -H "apikey: <publishable_key>" -H "Authorization: Bearer <publishable_key>"`
  Use `-H "Prefer: count=exact"` with `select=<col>` to get exact row counts from the
  `Content-Range` response header without pulling all rows.
- **Writes**: Do NOT write via the REST API with the publishable key. For INSERT/UPDATE/DELETE,
  still provide SQL for manual execution (the secret key is intentionally not used from here)
- **Always syntax-check code files before delivering**
- **Empty fields must insert as NULL, never empty string** — stager enforces this
- **source_import is sacred** — never TRUNCATE or DROP CASCADE from tables that reference it
  without verifying no FK points back. The 2026-06-12 incident: TRUNCATE ... CASCADE on
  composition wiped source_import via FK. Recovered from xlsx export.
- **Unique constraint on source_import** uses IS NOT DISTINCT FROM semantics —
  NULL vs empty string defeats it. Always normalise to NULL.
