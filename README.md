# StudentTracker GradFile — public reference implementation

This public snapshot contains code, specifications, synthetic test fixtures, and header-only templates. It contains no student extracts, returned reports, working credentials, or original project Git history. Account-routing constants beginning with `9000000`, the example login, and `example-studenttracker-bucket` are placeholders. Configure your own reviewed mappings and storage before operational use.

Prepare empty local input templates after cloning:

```sh
python3 prepare_local_templates.py
uv sync
uv run python -m unittest discover -s tests -p 'test_*.py'
```

The initializer copies the three files under `templates/` to their ignored local paths and never overwrites existing files. Keep real inputs out of commits. See [PUBLIC_RELEASE_REVIEW.md](PUBLIC_RELEASE_REVIEW.md), [account and report naming](docs/accounts_and_report_naming.md), and [workflow status](docs/workflow_status.md) for scope and limitations.

## Original workflow documentation

# StudentTracker Grad File to Share — 2026-11-10

This is a sanitized reference copy. Start with [SHARING_NOTES.md](SHARING_NOTES.md) for included/excluded content, setup, and limitations. No original student records or working credentials are included. The account-reference workbook and credential CSV contain headers only; the examples are invented.

Start with [supported workflows and remaining work](docs/workflow_status.md) to choose an entry point, and [account sources and report naming](docs/accounts_and_report_naming.md) for SA/ACT/CDS structure and returned-file naming rules. The workbook template preserves the original `Refs`, `NCES`, and `CDS` sheet headers.

# StudentTracker GradFile Runbook

## Prereqs / setup
- `creds.csv` is header-only in this share copy. Working credentials must be supplied privately in an authorized operational copy.
- Verify required inputs in `data/`:
  - `account_refs.xlsx`
  - Cohort parquet files (e.g., `ClassOf24-ClassOf27_152_cohort_outcomes.parquet`, `ClassOf25-ClassOf28_152_cohort_outcomes.parquet`)
  - Alvord lists in `data/alvord/` and `data/alvord/2025/`
- R packages used: `tidyverse`, `readxl`, `arrow`, `lubridate`, `stringi`, `odbc` (only in some scripts).

## Generate Alvord request files (AVID / IB / PUENTE)
Inputs:
- 23–24 lists:  
  - `data/alvord/IB Student Tracker.xlsx`  
  - `data/alvord/Puente Student Tracker.xlsx`  
  - `data/avid_2024.csv` (countywide; filtered to Alvord by CDS prefix)
- 24–25 lists:  
  - `data/alvord/2025/AVID Graduates 2024-25.xlsx`  
  - `data/alvord/2025/IB Graduates 2024-25.xlsx`  
  - `data/alvord/2025/Puente students 2024-25.xlsx`

Run:
```sh
Rscript 01g-processAlvord.R
```

Outputs (dated today):
- `requestfiles/YYYYMMDD_<SA>_ALVORDUNIFIEDSCHOOLDISTRICT_AVID.txt`
- `requestfiles/YYYYMMDD_<SA>_ALVORDUNIFIEDSCHOOLDISTRICT_IB.txt`
- `requestfiles/YYYYMMDD_<SA>_ALVORDUNIFIEDSCHOOLDISTRICT_PUENTE.txt`
- Test files in `requestfiles/test_file/`

## Generate countywide submission files
Annual `PH3`/`PD3` graduate submissions are intentionally single-class. The
generator stops before writing if the graduation-date window resolves to more
or less than one graduation class.

Run:
```sh
Rscript 01-process.R
```

The defaults retain the original Class 2025. For a new annual submission, set the class explicitly; the source path, September–August graduation window, and header school year follow that choice. Override the source path when its actual filename differs:

```sh
ST_COHORT_YEAR=2026 ST_RUN_DATE=20261110 \
  ST_COHORT_PATH=data/ClassOf26-ClassOf29_152_cohort_outcomes.parquet \
  Rscript 01-process.R
```

These settings apply to the annual submission script. Legacy program-request scripts retain their own settings. CHRT files currently stop the annual run pending a reviewed input crosswalk and charter-coverage registry; see REQ-18 and the workflow status document.

Outputs:
- `submissionfiles/YYYYMMDD_<SA>_<District>.txt`
- Test files in `submissionfiles/test_file/`
- `county_grad_w_accounts.rds`
- `county_cohort_summary.csv`
- `service_account_analysis.csv`

## Generate countywide AVID request files
The default AVID request combines Classes 2022 through 2025. Each class is
built from the same-year intersection of AVID course participants in the
countywide CALPADS 3.11 snapshot (State Course `9211`) and regular graduates
in the annual 15.2 Account extract. The generator reads these source pairs
from MinIO without modifying them and performs no SFTP operations.
Missing optional middle-name and suffix values are written as empty fields;
the serialized-file validator rejects placeholder values such as `NA` or `Null`.
Current SA, ACT, district, and school values are refreshed by CDS from
`data/account_refs.xlsx` on every run. Explicit single-class request configurations are allowed; use
the maintained Python generator for new requests.

```sh
ENV=prod uv run python 01x-process_avid_request.py \
  --run-date YYYYMMDD \
  --cohort-years 2022-2025 \
  --preflight-only
```

After reviewing the aggregate-only preflight, omit `--preflight-only` to write
the checksum-locked request set:

```sh
ENV=prod uv run python 01x-process_avid_request.py \
  --run-date YYYYMMDD \
  --cohort-years 2022-2025
```

Outputs:
- `requestfiles/YYYYMMDD_<SA>_<District>_AVID.txt`
- deterministic dated test files under `requestfiles/test_file/`
- `audit/YYYYMMDD_avid_request_source_manifest.csv` with both annual source
  objects' size, ETag, and SHA-256 for every class
- `audit/YYYYMMDD_avid_request_cohort_summary.csv` with per-class reconciliation
- `audit/YYYYMMDD_avid_request_summary.csv`
- `audit/YYYYMMDD_avid_request_blockers.csv`
- `audit/YYYYMMDD_avid_request_manifest.csv` with size and SHA-256
- `audit/YYYYMMDD_avid_request_upload_manifest.csv` containing production requests only

Review the aggregate summary and exact upload manifest before any upload. Upload
only the upload manifest's paths, using `filename_prefixes` to prevent other
request families from being selected.

## Generate summer CCR request files (AP / CC / IB / SSB)
Inputs:
- `data/ccrSummer2026/{2122,2223,2324,2425}/{AP,CC,IB,SSB}<class>.csv`
- `data/account_refs.xlsx`
- `data/sinf_merge.parquet`

Run:
```sh
uv run python 01w-process_ccr_summer_request.py --run-date YYYYMMDD
```

The generator writes separately suffixed request and test files plus a
date-scoped summary, blocker audit, duplicate audit, and checksum manifest
under `audit/`. Review those aggregate totals before uploading. Scope uploads
to the exact manifest filenames; successful upload states are retained under
`state/uploads/YYYYMMDD/request/` and should not be forced on a retry.

## Generate countywide multi-class CTE request files
The default CTE cohort combines Classes 2023 through 2025 from the annual
countywide CALPADS 15.2 Account extracts produced with the native
`CTE Completer = Y` filter. This keeps the three graduating classes in one CTE
request per service account while preserving each student's graduation date
and per-class audit lineage. MinIO access is read-only and defaults to the
`prod` profile.

Run an aggregate-only preflight first. It reads the source objects and local
account/name references but writes no request or student-level audit files:

```sh
ENV=prod uv run python 01y-process_cte_request.py \
  --run-date YYYYMMDD \
  --cohort-years 2023-2025 \
  --preflight-only
```

After reviewing the preflight totals, generate the locked request set:

```sh
ENV=prod uv run python 01y-process_cte_request.py \
  --run-date YYYYMMDD \
  --cohort-years 2023-2025
```

Class 2026 has a current filtered 15.2 CTE source but is opt-in; select
`--cohort-years 2023-2026` only when that newly graduated class belongs in the
StudentTracker results cycle. CTE configurations with fewer than three classes
are rejected before source reads or local writes.

Outputs:
- `requestfiles/YYYYMMDD_<SA>_<District>_CTE.txt`
- deterministic test files under `requestfiles/test_file/`
- `audit/YYYYMMDD_cte_request_source_manifest.csv` with source URI, ETag,
  byte count, and SHA-256 for each filtered annual 15.2 CTE object
- `audit/YYYYMMDD_cte_request_cohort_summary.csv` with per-class source,
  regular-graduate, blocker, and outbound totals
- date-scoped overall summary, graduate-duplicate audit, blocker audit,
  request manifest, and production-only upload manifest

Review the aggregate summary and exact upload manifest before any upload. The
generator performs no MinIO writes and no StudentTracker SFTP transfer.

## Upload files (SFTP)
Use `02-upload.py` helpers (per-account state is stored by date).

Upload request files:
```sh
python3 - <<'PY'
from datetime import date
from importlib import import_module

m = import_module("02-upload")
m.upload_requests(
    m.creds,
    request=True,
    run_date=date.today().strftime("%Y%m%d"),
    cohort_years=(2022, 2023, 2024, 2025),
)
PY
```

Upload submission files:
```sh
python3 - <<'PY'
from datetime import date
from importlib import import_module

m = import_module("02-upload")
m.upload_requests(
    m.creds,
    request=False,
    run_date=date.today().strftime("%Y%m%d"),
    cohort_years=(2025,),
)
PY
```

An authentication failure records the current account as failed and stops the
entire multi-account upload run. Check VPN/location and credential status before
retrying; use `force=True` only after the cause is resolved.

## Download reports
```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
m.download_files(m.date, m.creds)
PY
```

Downloads also stop on the first authentication failure so one location or
credential-policy problem cannot trigger repeated login attempts across district
accounts.

Outputs go to `downloads/<YYYYMMDD>/<district>/`.

## Scaffold returned report types
Use this after downloading a new batch when NSC returns multiple unlabeled report sets and not every district necessarily has every type.

```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
rows = m.scaffold_report_types("YYYYMMDD")
print(f"Scaffolded {len(rows)} detail files")
PY
```

Output:
- `downloads/<YYYYMMDD>/report_type_scaffold.csv`

Notes:
- The scaffold compares returned `DETAIL` files to the exact student rosters that were sent for the known source batches in this repo:
  - `submissionfiles/20260127_*.txt` as `SPRING_REGULAR`
  - `requestfiles/20260422_*.txt` as `MIGRANT`
  - `requestfiles/20260422_*_SELPA.txt` as `SELPA`
- Matching is intentionally conservative. A row is auto-labeled only when the student fingerprint overlap is strong; otherwise it stays `UNKNOWN` and the `top_candidates` column shows the best hints for manual review.
- `related_download_files` lists other files in the same district / SA / `EFFDT` / `RUNDT` bucket so the scaffold can be used to group a `DETAIL` file with its companion report bundle.

## Check `receive-archive` for older returns
```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
m.inventory_receive_archive(
    m.creds,
    output_path=f"downloads/{m.date}/receive_archive_inventory.json",
)
PY
```

To download archive-only files that are not already present under `downloads/<YYYYMMDD>/<district>/`:
```sh
python3 - <<'PY'
from importlib import import_module
import json

m = import_module("02-upload")
with open(f"downloads/{m.date}/receive_archive_inventory.json", encoding="utf-8") as f:
    inventory = json.load(f)
m.download_receive_archive_missing(
    m.date,
    m.creds,
    inventory=inventory,
    output_path=f"downloads/{m.date}/receive_archive_downloads.json",
)
PY
```

Notes:
- The archive inventory is non-destructive and records per-district file lists plus any connection errors.
- Archive downloads only fetch files missing from the current local download folder.

## Expand / rename reports (optional)
```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
# Use filter_rundt to only process files from this run date.
m.expand_and_rename(eff_date=m.date, filter_rundt=m.date)
PY
```

Today-download / this-month EFFDT example:
```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
m.expand_and_rename(eff_date=m.date, filter_effdt=m.date[:6])
PY
```

Notes:
- Renamed files now include `EFFDT..._RUNDT...` in the filename to prevent collisions when multiple batches exist in the same `downloads/<date>/<district>/` folder.
- Re-running `expand_and_rename` is idempotent for already-renamed `NSC_...` files.
- `DETAIL` CSVs are moved into `processed/<date>/<district>/detail/` and renamed as `NSC_<district>_Detail_<sa>_<job>_EFFDT..._RUNDT....csv` so they are separated from `reports/`.

## Organize downloaded results by type then district
After the scaffold exists, this copies the matching `DETAIL` file and its job-matched ZIP bundle into a separate sorted tree without touching the raw download:

```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
m.organize_results_by_type("YYYYMMDD")
PY
```

Output:
- `downloads/YYYYMMDD_sorted/MIGRANT/<district>/...`
- `downloads/YYYYMMDD_sorted/SELPA/<district>/...`
- `downloads/YYYYMMDD_sorted/SPRING_REGULAR/<district>/...`
- `downloads/YYYYMMDD_sorted/UNKNOWN/<district>/...`
- `downloads/YYYYMMDD_sorted/UNCLASSIFIED/<district>/...`

Notes:
- ZIP files are paired to a batch type using the NSC job id embedded inside the ZIP contents.
- `UNKNOWN` is expected when the scaffold found a candidate but the evidence was not strong enough to auto-label it.
- `UNCLASSIFIED` is used for any leftover file that could not be attached to a scaffolded batch at all.

## Process Class-of-2025 CTE returns
Stage only the exact CTE DETAIL/ZIP pairs under
`downloads/YYYYMMDD_sorted/CTE/<district>/`. The DETAIL roster must exactly
match `requestfiles/20260828_<SA>_*_CTE.txt`, and the ZIP's internal NSC job id
must match the selected DETAIL job. Do not use a same-day filename alone when
AVID and CTE returns coexist under one account.

```sh
python3 - <<'PY'
import importlib.util
from pathlib import Path

m_spec = importlib.util.spec_from_file_location("studenttracker_upload", "02-upload.py")
m = importlib.util.module_from_spec(m_spec)
m_spec.loader.exec_module(m)
cte_accounts = [
    row for row in m.creds
    if list(Path("requestfiles").glob(
        f"20260828_{row['sa']}_*_CTE.txt"
    )
]
m.expand_and_rename(
    eff_date="20260828_sorted/CTE",
    suffix=m.CTE_REPORT_SUFFIX,
    filter_rundt="20260828",
    filter_effdt="20260820",
    header_text=m.CTE_REPORT_HEADER,
    creds_override=cte_accounts,
)
PY
```

Outputs:
- `processed/YYYYMMDD_sorted/CTE/<district>/detail/` for isolated DETAIL CSVs
- `processed/YYYYMMDD_sorted/CTE/<district>/reports/` for renamed and watermarked reports
- `processed/YYYYMMDD_sorted/CTE/<district>/<district>_CTE_renamed.zip` for reports-only delivery

## Extract migrant districtwide BASIC reports
Use this after the sorted tree exists. It pulls the districtwide `BASIC` `.xls` and companion `.pdf` out of the migrant ZIPs into a working folder for downstream report-building.

```sh
python3 - <<'PY'
from importlib import import_module

m = import_module("02-upload")
m.extract_migrant_districtwide_basic_reports("YYYYMMDD")
PY
```

Output:
- `migrant_workflow/data/excel/NSC_<District>__Districtwide_Basic.xls`
- `migrant_workflow/data/pdf/NSC_<District>__Districtwide_Basic.pdf`
- `migrant_workflow/migrant_districtwide_basic_manifest.csv`

Notes:
- The extractor only pulls the districtwide `BASIC` files where the internal NSC ACT token matches the service-account token, so school-level `BASIC` exports are ignored.
- Re-running the extractor replaces the same district-level outputs with the most recent files from the chosen sorted migrant set.

## Parse migrant districtwide BASIC reports into `All` / `MCI` metrics
This reads the extracted districtwide `BASIC` `.xls` files, normalizes the sparse summary blocks, and writes machine-friendly CSVs that can be used to build the migrant workbook or feed the downstream RMarkdown pipeline.

Run:
```sh
Rscript 12-parse_migrant_basic_reports.R
```

Optional custom input/output paths:
```sh
Rscript 12-parse_migrant_basic_reports.R \
  migrant_workflow/data/excel \
  migrant_workflow/parsed
```

Outputs in `migrant_workflow/parsed/`:
- `all_sheet_district_metrics.csv`
- `all_sheet_county_metrics.csv`
- `all_sheet_progress_district_metrics.csv`
- `all_sheet_progress_county_metrics.csv`
- `all_sheet_persistence_district_metrics.csv`
- `all_sheet_persistence_county_metrics.csv`
- `mci_district_candidates.csv`
- `mci_county_candidates.csv`
- `parse_summary.csv`

Notes:
- The parser handles districts with different class-year spans by dropping empty columns inside each report block before reshaping.
- The `MCI` parser reads the sparse header columns directly from the districtwide `BASIC` sheets and outputs `Name`, `Rank`, `State`, `Level`, `Type`, and `Total`.
- The countywide `mci_county_candidates.csv` file is summed across districts and ranked by total students, so it is much closer to a direct `MCI Final` input than the earlier name-only prototype.

## Build a migrant workbook with `All` and `MCI Final` tabs
After parsing the districtwide `BASIC` files, build a consolidated workbook from the county-level CSVs:

```sh
.venv/bin/python 13-build_migrant_workbook.py
```

Output:
- `migrant_workflow/output/_All2026.xlsx`

Notes:
- The builder writes a fresh `All` sheet and `MCI Final` sheet from the parsed county metrics instead of relying on the old hand-maintained formula tabs.
- The workbook includes the full MCI fields from the raw `BASIC` sheets: `Name`, `Rank`, `State`, `Level`, `Type`, and `Total`.
- The year coverage is driven by the current parsed data, so newer cohorts such as `2024` and `2025` are included where present.

## Retry behavior
Per-account state is stored by date:
- Upload state: `state/uploads/<YYYYMMDD>/submission/` and `state/uploads/<YYYYMMDD>/request/`
- Download state: `state/downloads/<YYYYMMDD>/download/`

To retry a single account, delete its state file or call the helper with `force=True`.

## Rancho Mirage SMART special request
`01z-process_smart_request.py` reads the supplied Class 2025 workbook as district
LocalIDs and matches Palm Springs Unified / Rancho Mirage High records to raw
SSIDs. It writes one `_SMART` request, a deterministic test file, and local
roster, exclusion, blocker, and checksum audits. It performs no upload.

The 2026-10-28 run includes 14 students and excludes one source student at the
user's direction. Its invocation and source checksums are recorded in the
SMART audit artifacts. Single-class special requests are valid (REQ-30, DEC-39).
