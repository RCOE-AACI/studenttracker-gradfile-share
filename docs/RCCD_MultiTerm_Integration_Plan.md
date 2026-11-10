# RCCD Multi-Term Integration Plan (StudentTracker GradFile)

## Goal
Integrate the RCCD enrollment ingestion + SSID matching workflow from `../20250129 RCCD Enrollment Process` into this project so `11-Detail.R` can consume **one consolidated** `data/rccd_matched_ssid.parquet` that automatically includes all terms under `data/RCCD/` (e.g., `24FAL/`, `25SPR/`, `25FAL/`) without per-term code changes.

Constraints/decisions:
- Date of birth matching stays **exact** (no tolerance window).
- Output is a **single consolidated parquet** once matches are established.
- SINF source for matching is **this repo’s** `data/cumulative_sinf.parquet` (not the sibling project’s copy).

## Current State
- `11-Detail.R` expects RCCD data with an `SSID` column at `data/rccd_matched_ssid.parquet` (`11-Detail.R:351`).
- Existing RCCD matching code lives in `../20250129 RCCD Enrollment Process/02-MatchAndFilter.R`:
  - Blocks by DOB then uses Jaro-Winkler distance on first/last names.
  - Selects best match per `College Student ID` and writes `rccd_matched_ssid.parquet`.
- Newer terms in this repo are stored as **three campus CSVs per term** under `data/RCCD/<TERM>/` (e.g., `00127000.csv`, `04173500.csv`, `04176100.csv`), while older term(s) may be a single parquet.

## Deliverables
1. `data/rccd_matched_ssid.parquet` (consolidated; all terms; includes `SSID`).
2. `data/rccd_college_id_ssid_crosswalk.parquet` (stable crosswalk to prevent re-deciding matches every term).
3. Optional: `data/rccd_match_overrides.csv` (manual overrides for exceptional cases; replaces hard-coded vectors).
4. A small, runnable RCCD build script (R) that:
   - reads all `data/RCCD/*`
   - updates crosswalk
   - writes the consolidated parquet
   - emits a term-level QA report.

## Proposed File Layout (new)
- `rccd/ingest_terms.R`
  - `rccd_list_terms(rccd_root = "data/RCCD")`
  - `rccd_read_term(term_dir, term_code = basename(term_dir))`
  - `rccd_read_all_terms(rccd_root = "data/RCCD")`
- `rccd/match_to_sinf.R`
  - `sinf_load_relevant(sinf_path = "data/cumulative_sinf.parquet", dob_values = NULL)`
  - `rccd_apply_crosswalk(rccd_tbl, crosswalk_tbl)`
  - `rccd_fuzzy_match_new_ids(rccd_tbl, sinf_tbl, weights = c(first = 0.25, last = 0.75), accept = list(max_score = 0.20, min_margin = 0.03))`
  - `rccd_apply_overrides(rccd_tbl, overrides_path = "data/rccd_match_overrides.csv")`
- `rccd/build_consolidated.R` (entrypoint)
  - orchestrates ingest + match + outputs.

Notes:
- Keep the implementation in R to align with `11-Detail.R` and avoid Python dependency drift.
- We can vendor only the essential logic from `../20250129 RCCD Enrollment Process/02-MatchAndFilter.R` (no need for `.CLR` parsing unless future terms arrive in that format).

## Canonical RCCD Term Schema Contract
`rccd_read_term()` must return a tibble containing at least:
- `Academic Term` (e.g., `24FAL`, `25SPR`, `25FAL`)
- `College Student ID`
- `First Name`
- `Last Name`
- `Date of Birth`
- `School Code`
- `Branch Code`
- `Term Begin Date`
- `Term End Date`

And it must add:
- `College_Code/Branch = paste0(\`School Code\`, "-", \`Branch Code\`)` (matches `11-Detail.R` usage)

Implementation detail:
- When reading term CSVs, use `col_types = cols(.default = col_character())` to preserve leading zeros and avoid type drift.
- Normalize `Date of Birth` and `Student Birth Date` with `lubridate::ymd()` when computing matches, but keep original strings in the output if downstream expects them.

## Matching Strategy (exact DOB; stable over time)
### Crosswalk-first approach
Maintain a durable mapping by `College Student ID`:
- `data/rccd_college_id_ssid_crosswalk.parquet` columns:
  - `College Student ID` (string)
  - `SSID` (string)
  - `match_source` (`crosswalk|fuzzy|override`)
  - `match_score` (numeric; optional for crosswalk rows)
  - `first_term`, `last_term` (term codes)
  - `updated_at` (timestamp)

Algorithm:
1. Ingest all RCCD rows from `data/RCCD/*`.
2. Left-join crosswalk onto RCCD by `College Student ID` to fill existing `SSID` immediately.
3. For RCCD rows still missing `SSID`, fuzzy match using:
   - **blocking**: exact DOB only
   - **scoring**: normalized string distance on first/last names (prefer Jaro-Winkler if `stringdist` is available; otherwise normalized Levenshtein via `adist()` works)
   - **name variants**: compare RCCD names against SINF legal + alias + preferred; use the minimum distance per candidate (reduces false negatives without widening DOB).
4. **acceptance gate** (to avoid false positives as terms grow):
   - accept match if `best_score <= max_score` **and** `(second_best_score - best_score) >= min_margin`
   - else mark `ambiguous` and leave `SSID` as `NA` (optionally write a review CSV/parquet).
5. Apply overrides (if present) last; update crosswalk.
6. Write consolidated `data/rccd_matched_ssid.parquet` with the new `SSID` values.

### Parameter tuning surface
Keep parameters centralized (single list) so they’re easy to tune:
- weights: `first = 0.25`, `last = 0.75`
- accept thresholds: `max_score`, `min_margin`
- candidate cap: keep top N candidates per `College Student ID` for debug output.

## Output Content
`data/rccd_matched_ssid.parquet` should contain:
- all original RCCD fields (as ingested)
- `SSID`
- optional diagnostics:
  - `match_status` (`matched|ambiguous|unmatched|crosswalk|override`)
  - `match_score`, `match_margin`, `match_rank`
  - `matched_sinf_*` (e.g., matched legal names) only if needed for auditing (otherwise keep in a separate candidates file).

## `11-Detail.R` Integration Plan
1. Keep `rcc_detail <- load_rcc(path = "data/rccd_matched_ssid.parquet")` (no change to the contract).
2. Remove the hard-coded `RCC_TERM_START` dependency and instead de-dup RCCD vs NSC on:
   - keys: `(SSID, Enrollment_Begin, College_Code/Branch)`
   - where `Enrollment_Begin` is `Term Begin Date` carried through `convert_rcc_to_nsc()`.
3. Move the special-case `College Student ID`/`SSID` fixes (currently in `load_rcc()` in `11-Detail.R`) into `data/rccd_match_overrides.csv` so new terms don’t require code edits.

## QA / Validation Checklist
The build script should print (and optionally write) a compact QA table per term:
- `rows_total`
- `distinct_college_student_id`
- `distinct_ssid_matched`
- `pct_ssid_missing`
- duplicate counts on `(College Student ID)` and `(SSID, Term Begin Date, College_Code/Branch)`

Hard stops (fail the build) if:
- a term ingests zero rows
- required columns are missing
- a new term has `pct_ssid_missing` above a configurable threshold (e.g., > 90%) after matching (signals schema changes or SINF mismatch).

## Implementation Steps (execution order)
1. Create `rccd/ingest_terms.R` to read `data/RCCD/*` robustly (parquet or 3-campus CSVs).
2. Port and refactor matching logic into `rccd/match_to_sinf.R`, changing SINF path to `data/cumulative_sinf.parquet`.
3. Add crosswalk persistence (`data/rccd_college_id_ssid_crosswalk.parquet`) and optional overrides file support.
4. Add `rccd/build_consolidated.R` that generates the consolidated parquet + QA summary.
5. Update `11-Detail.R` to rely on the consolidated parquet and remove single-term assumptions in de-duping logic.

## Acceptance Criteria
- Running `Rscript rccd/build_consolidated.R` produces `data/rccd_matched_ssid.parquet` that includes all terms present under `data/RCCD/`.
- `11-Detail.R` runs without needing term-specific RCCD code edits as new `data/RCCD/<TERM>/` folders are added.
- Crosswalk prevents previously-established `College Student ID -> SSID` mappings from shifting when new terms arrive.
