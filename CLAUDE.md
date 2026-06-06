# Musikk Katalog Database - Claude Code Context

## Project Overview

Norwegian historical music catalogue database. Sheet music metadata from Norwegian/Nordic publishers,
primarily 1800s–early 1900s. Source data from University of Oslo (hf.uio.no).
Separate from the live music scores project (Supabase project: tfqnzszyjsdgdeksizel).

## Infrastructure

- **Supabase**: Separate project from live music database
- **PostgreSQL schema**: `public` (own project, no prefix needed)
- **Table names**: ALL LOWERCASE in REST API
- **Frontend**: To be built — separate HTML/JS files, own `SUPABASE_URL` and `SUPABASE_KEY`

-----

## Database Schema

### person

- person_id (PK, autoincrement)
- last_name (text)
- first_name (text, nullable — may be initials only e.g. “B C”)
- person_type (text) — ‘person’ | ‘anon’ | ‘collection’
  - `anon` = unknown composer (“Anon” in source)
  - `collection` = multiple composers, editor unknown or secondary (“NN” in source)
- born (integer, nullable) — aligned to live music database field name
- bio_text (memo, nullable) — aligned to live music database field name
- notes (text, nullable)

### pseudonym

Separate table (not a single text field) to support multiple aliases per person with attribution notes.

- pseudonym_id (PK, autoincrement)
- person_id (FK → person)
- pseudonym_name (text) — e.g. “Lago, N”
- pseudonym_source (text) — notes on attribution

Known pseudonyms from source:

|Pseudonym       |Real name                |
|----------------|-------------------------|
|Aletter, Wilhelm|Alphonse Tellier         |
|Bachmann, G     |Fr. Behr                 |
|Bolt, Finn      |Sigurd Lie               |
|Bonheur, Theo   |Thomas Bulch             |
|Brown, Elisa    |L. Solberg               |
|Clarelius       |Alfred Paulsen           |
|d’Avout, Fanny  |Fanny Egeberg            |
|Grahl C G       |G C W Prahl              |
|Ika             |Albertina Fredrika Peyron|
|Lago, N         |Laura Netzel             |
|Lambert, Leon   |Alfred Paulsen           |
|Morley, Ch      |Fr Behr                  |
|Nesrednah       |H Andersen               |
|Petroe, Emil    |Emil Petersen            |
|Pomposi, Ernesto|Christian Teilman        |
|Wilhelmine      |Wilhelmine Sørlie        |

### composition

Core intellectual work record.

- composition_id (PK, autoincrement)
- publisher_id (FK → publisher, nullable)
- instrumentation_id (FK → instrumentation, nullable)
- title (text 500) — aligned to live database; standardized orthography; text before “/” in source
- subtitle (text 500, nullable) — parsed from “/” separator in source title string
- plate_number (text 100) — not sortable; space-separated numbers; dash notation for 3+ numbers
- year_issued (text 20) — publication date / range start
- year_issued_end (text 20, nullable) — only for year ranges e.g. “1860 - 1869”
- year_qualifier (text) — ‘exact’ | ‘circa’ | ‘before’ | ‘decade’ | ‘range’
  - `1852` → exact
  - `1852c` → circa
  - `1852f` → before (displays as –1852)
  - `185*` → decade (1850–1859)
  - `1860 - 1869` → range (use year_issued + year_issued_end)
- month (text 20, nullable) — sorts alphabetically, not chronologically
- raw_instrumentation (text 100, nullable) — fallback for combinations not matching any instrumentation code
- composition_notes (text, nullable) — aligned to live database; includes former publisher info

### composition_person

Many-to-many join between composition and person with role.
Field names aligned to live music database.

- id (PK, autoincrement)
- composition_id (FK → composition)
- person_id (FK → person)
- role (text) — ‘Composer’ | ‘Lyricist’ | ‘Arranger’ | ‘Editor’
- credited_as (text, nullable) — name variant as printed on the score; aligned to live database
- is_primary (boolean) — main credited person

**Import note**: Lyricist/author names embedded in source title strings as `(Initial Surname)`
e.g. `3 Digte op.2 /Serenade (J Moe)` → extract `J Moe` as a `composition_person` row
with `role = 'Lyricist'`.

### publisher

- publisher_id (PK, autoincrement)
- publisher_name (text) — aligned to live database field name
- city (text) — default: Christiania (unless otherwise specified in source)
- country (text, nullable)
- is_self_published (boolean) — TRUE for “Eget” in source data
- is_unknown (boolean) — TRUE for “ukjent” in source data

### instrumentation

Full Norwegian text as primary value. Legacy codes kept for import mapping only.

- instrumentation_id (PK, autoincrement)
- description_no (text) — PRIMARY e.g. “fløyte og piano”
- description_en (text, nullable) — e.g. “flute and piano”
- legacy_code (text 50) — e.g. “fl-p”; import mapping only, can be deprecated post-migration
- category (text) — ‘choir’ | ‘solo’ | ‘ensemble’ | ‘school’
- is_school_book (boolean) — TRUE for method/tutor books

**Seed data — full instrumentation table:**

|legacy_code|description_no     |description_en      |category|
|-----------|-------------------|--------------------|--------|
|2s-p       |to stemmer og piano|two voices and piano|ensemble|
|2st        |tostemmig kor      |two-part choir      |choir   |
|3st        |trestemmig kor     |three-part choir    |choir   |
|blkor      |blandet kor        |mixed choir         |choir   |
|cor        |horn               |horn                |solo    |
|dkor       |damekor            |ladies’ choir       |choir   |
|fl-p       |fløyte og piano    |flute and piano     |ensemble|
|git        |gitar              |guitar              |solo    |
|harm       |harmonium          |harmonium           |solo    |
|mkor       |mannskor           |men’s choir         |choir   |
|org        |orgel              |organ               |solo    |
|ork        |orkester           |orchestra           |ensemble|
|p2         |tohendig piano     |piano two hands     |solo    |
|p4         |firhendig piano    |piano four hands    |solo    |
|s-p        |sang og piano      |voice and piano     |ensemble|
|strkva     |strykekvartett     |string quartet      |ensemble|
|vc-p       |cello og piano     |cello and piano     |ensemble|
|vn-p       |fiolin og piano    |violin and piano    |ensemble|

**Note on codes**: Codes are NOT mechanically decomposable by a single rule.
`p4` = piano four hands (not p + 4). `2s-p` = two voices + piano. Treat each code as opaque.
Bare instrument codes (`fl`, `vn`, `p`, `vc`) may appear in source data without a matching
compound code — store in `composition.raw_instrumentation` as fallback.

### periodical

Named journal series.

- periodical_id (PK, autoincrement)
- title (text) — full title
- abbreviation (text 50) — e.g. “NMT”, “MLM”
- ref_format (text) — parsing pattern description
- notes (text, nullable) — e.g. continuation relationships between journals

Known periodicals from source:

|title                      |abbreviation|notes                                                     |
|---------------------------|------------|----------------------------------------------------------|
|Den norske Lyra            |DNL         |ref format: 4-digit YYMM e.g. 2510 = Oct 1825             |
|Lyra                       |—           |ref format: h.XYZ = vol X issue YZ                        |
|Musikalsk Album            |MA          |ref format: h.XYZ; NR = ny rekke; TrR = tredje rekke      |
|Musikalsk Løverdags-Magazin|MLM         |ref format: h.XYZW complex; see periodical_issue          |
|Musikalsk Nyhedsblad       |MN          |Direct continuation of MLM                                |
|Nordisk Musik-Tidende      |NMT         |Plate numbers from publisher protocols, repeated per issue|
|Nyt Musikalsk Museum       |NMM         |ref format: h.XYZ = vol X issue YZ                        |
|Amphion                    |—           |                                                          |

### periodical_issue

Individual issues within a periodical.

- issue_id (PK, autoincrement)
- periodical_id (FK → periodical)
- raw_reference (text 50) — original string e.g. “h.101”, “NR h.02”, “2510”
- series_label (text 50, nullable) — ‘NR’ (ny rekke) | ‘TrR’ (tredje rekke) | null
- volume (smallint, nullable) — årgang
- issue_number (smallint, nullable) — hefte
- division (smallint, nullable) — avdeling (MLM only)
- section (smallint, nullable) — rekke (MLM only)

**Reference parsing rules:**

- `h.101` → volume=1, issue_number=1
- `h.306` → volume=3, issue_number=6
- `NR h.02` → series_label=‘NR’, issue_number=2
- `h.0102` → volume=1, issue_number=2 (MLM style — leading zero)
- `h.1201` → division=1, section=2, issue_number=1 (MLM style)
- `2510` → Den norske Lyra: month=Oct, year=1825

### composition_issue

Many-to-many join between composition and periodical issue.

- composition_id (FK → composition)
- issue_id (FK → periodical_issue)
- plate_number_in_issue (text 100, nullable) — NMT repeats plate number per issue

### former_publisher

Ordered publication history per composition. Extracted from composition_notes on import.

- former_pub_id (PK, autoincrement)
- composition_id (FK → composition)
- publisher_id (FK → publisher)
- sequence (smallint) — ordering (1 = earliest)
- notes (text, nullable)

-----

## Relationships

- Person 1─∞ Pseudonym
- Person ∞─∞ Composition via composition_person (with role)
- Publisher 1─∞ Composition
- Instrumentation 1─∞ Composition
- Periodical 1─∞ PeriodicalIssue
- Composition ∞─∞ PeriodicalIssue via composition_issue
- Composition 1─∞ FormerPublisher
- Publisher 1─∞ FormerPublisher

-----

## Source Data Format

### Search result columns (tab-separated export):

`Person | Rolle | Tittel | Besetning | Forlag | Platenr | Utgivelsesår | Måned | Periodikum | Kommentar`

### Column mapping to schema:

|Source column|Table                        |Field                                         |
|-------------|-----------------------------|----------------------------------------------|
|Person       |person                       |last_name + first_name (format: “Last, First”)|
|Rolle        |composition_person           |role                                          |
|Tittel       |composition                  |title (+ subtitle after “/”)                  |
|Besetning    |instrumentation              |legacy_code → instrumentation_id              |
|Forlag       |publisher                    |publisher_name                                |
|Platenr      |composition                  |plate_number                                  |
|Utgivelsesår |composition                  |year_issued (+ year_qualifier)                |
|Måned        |composition                  |month                                         |
|Periodikum   |periodical + periodical_issue|title + raw_reference                         |
|Kommentar    |composition                  |composition_notes                             |

### Import transformation rules:

1. **Person name**: Split “Last, First” on first comma → last_name, first_name
1. **Title with subtitle**: Split on “/” → title, subtitle
1. **Lyricist in title**: Extract “(Initial Surname)” from title → composition_person row, role=‘Lyricist’
1. **Year range**: “1860 - 1869” → year_issued=1860, year_issued_end=1869, year_qualifier=‘range’
1. **Periodikum**: Split on last space before “h.” or digit pattern → periodical title + raw_reference
1. **Besetning**: Look up legacy_code in instrumentation table → instrumentation_id; if no match → raw_instrumentation
1. **Forlag “Eget”**: → publisher row with is_self_published=TRUE
1. **Forlag “ukjent”**: → publisher row with is_unknown=TRUE
1. **Forlag default city**: Christiania unless otherwise stated

-----

## Field Name Alignment with Live Music Database

Fields intentionally aligned to `public` schema in live Supabase project (tfqnzszyjsdgdeksizel):

|This database    |Live database    |Table             |
|-----------------|-----------------|------------------|
|born             |born             |person            |
|bio_text         |bio_text         |person            |
|title            |title            |composition       |
|composition_notes|composition_notes|composition       |
|publisher_name   |publisher_name   |publisher         |
|composition_id   |composition_id   |composition_person|
|person_id        |person_id        |composition_person|
|role             |role             |composition_person|
|credited_as      |credited_as      |composition_person|

-----

## SQL Setup

```sql
-- Required grants for new tables
GRANT SELECT ON public.table_name TO anon, authenticated;
```

## Python API Pattern

```python
import requests

SUPABASE_URL = "https://<your-project>.supabase.co"
API_KEY = "<your-publishable-key>"
HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# SELECT
r = requests.get(f"{SUPABASE_URL}/rest/v1/composition?select=*", headers=HEADERS)

# INSERT
r = requests.post(f"{SUPABASE_URL}/rest/v1/composition", headers=HEADERS, json={...})
```