# Cruft Audit - StudentTracker GradFile

Historical June 2026 audit. For current sharing-copy implementation status, use [workflow_status.md](workflow_status.md); its reconciled status supersedes implementation and size assumptions below.

Generated 2026-06-12 after the EARS interview pass. This file identifies
candidate cleanup targets; it is not a deletion plan by itself. Student-level
source, output, and returned-report files may be subject to retention or local
handoff needs.

Refined 2026-06-12: this project recurs by copying a prior annual folder
forward. Some apparent cruft is copied-forward annual residue rather than a
single-year mistake. The Fall 2026 project copy is the best point to cull
prior-year outputs, stale one-off request scripts, and old source files that
are not needed for the new run.

Boundary decision: leave this folder intact. Use this audit as guidance for the
Fall 2026 copied folder when generation begins; do not clean or refactor the
current folder merely because a file is listed below.

## Summary

The workspace is about 14 GB. The largest directories are generated or archived
run artifacts:

| Path | Approx size | Classification |
|---|---:|---|
| `processed/` | 4.4 GB | generated sorted/renamed report outputs |
| `downloads/` | 2.8 GB | downloaded NSC return files and manifests |
| `data/` | 2.6 GB | mixed source inputs, reference files, and generated support files |
| `.venv/` | 132 MB | local Python environment |
| `full_detail/` | 46 MB | generated detail outputs |
| `migrant_workflow/` | 17 MB | mixed workflow inputs, parsed outputs, final workbook |
| `submissionfiles/` | 12 MB | generated outbound annual submissions |
| `requestfiles/` | 3.6 MB | generated outbound request files |

## High-Confidence Cleanup Candidates

These appear superfluous as source code or project logic.

| Path | Why it looks superfluous | Suggested action |
|---|---|---|
| `main.py` | Six-line uv scaffold that only prints `Hello from 20240829-studenttracker-gradfile!`; not referenced by the runbook or spec. | Delete after confirming no external command invokes it. |
| `03-watermark.py` | Duplicates watermark helpers in `02-upload.py`; main block hard-codes `processed/20250123/`, hard-codes an AVID label, and applies it twice. This conflicts with `REQ-23` / `DEC-24`. | Retire/delete after confirming `expand_and_rename(..., header_text=...)` covers the remaining watermark use case. |
| `.DS_Store` files | macOS metadata, not source. Present in many directories. | Delete locally and add `.DS_Store` to `.gitignore`. |
| `.RData`, `.Rhistory`, `.Rproj.user/` | RStudio/session state, not source. `.Rproj.user` is already ignored; `.RData` and `.Rhistory` are not. | Delete locally and add `.RData` / `.Rhistory` to `.gitignore`. |
| `__pycache__/` | Python bytecode cache. Already ignored by `.gitignore`. | Delete locally. |
| `.venv/` | Local virtual environment. Already ignored by `.gitignore`. | Keep locally if useful, but do not treat as project source. |

## Likely Superseded Code

These are not safe to delete blindly, but the current spec/runbook points to
newer replacements.

| Path | Current evidence | Suggested action |
|---|---|---|
| `01t-processTVUSD.R` | Older TVUSD request generator using `data/TVUSD Postsecondary Students 2023.24.xlsx` and older cohort files. The newer `01v-process_tvusd_request.py` implements blockers/audit files and is cited by `REQ-05`, `REQ-06`, and `REQ-07`. | Move to `archive/legacy/` or delete after confirming the 2023-24 TVUSD rerun path is no longer needed. |
| `data/TVUSD Postsecondary Students 2023.24.xlsx` | Used by `01t-processTVUSD.R`; newer TVUSD workflow uses `data/TVUSDClass2025.csv`. | Archive/delete with `01t-processTVUSD.R` if old TVUSD flow is retired. |

## Standard Annual Request Code To Keep Or Modernize

These files may look like one-off variants, but the requirement refinement says
standard annual request cohorts are part of the recurring process. They should
be cleaned up into a parameterized annual workflow, not discarded merely because
they came from a prior folder.

| Path | Current evidence | Suggested action |
|---|---|---|
| `01d-processAVID.R` | Countywide AVID is a standard annual request cohort. The current script reads `county_grad_w_accounts.rds` and `data/AVID_GRADS.rds`, so it is older and less self-contained than the Alvord-specific workflow. | Keep or modernize for Fall 2026; do not delete unless countywide AVID is replaced by a new standard request generator. |
| `01m-process_foster_request.R` | Standard Foster request cohort from official 15.2 records. | Keep, but parameterize annual dates/source files and shared helpers. |
| `01n-process_migrant_request.R` | Standard Migrant request cohort and feeds the migrant report workflow. | Keep, but parameterize annual dates/source files and shared helpers. |
| `01s-process_seal_biliteracy.R` | Recurring program cohort pattern similar to Foster/Migrant. | Keep if Seal of Biliteracy remains in the annual standard set; otherwise classify explicitly as optional/ad-hoc. |
| `data/AVID_GRADS.rds` | Used by the current countywide AVID script. | Keep until countywide AVID is modernized; then replace with project-year source files or a manifest entry. |

## One-Off Or Diagnostic Code To Review

These may still be useful, but they look like project-specific one-offs or
diagnostics rather than durable pipeline entrypoints.

| Path | Current evidence | Suggested action |
|---|---|---|
| `01u-processMVUSD.R` | MVUSD CTE request generator. It is still cited by `REQ-07`, but it is a district/project request rather than a standard annual request cohort. | Keep while MVUSD CTE reruns are plausible; otherwise archive after documenting the source file and output contract. |
| `rccd/compare_top25_methods.R` | Diagnostic comparison of districtwide versus school-summed Top25 reports; writes `_top25_method_compare...` files under `processed/<EFF_DATE>/`. | Keep only if the Top25 method comparison remains an active recurring check; otherwise archive as analysis history. |
| `rccd/diagnose_top25_gap.R` | Diagnostic lower-bound comparison for RCCD Top25 counts; writes `_rccd_top25...` outputs. | Keep only if this diagnostic will be rerun; otherwise archive. |
| `rccd/build_consolidated.R`, `rccd/ingest_terms.R`, `rccd/match_to_sinf.R` | These implement the RCCD consolidated parquet flow described in `docs/RCCD_MultiTerm_Integration_Plan.md` and feed `REQ-16`. | Keep. They are support pipeline code, not cruft. |

## Repetition That Should Be Consolidated, Not Deleted

The following scripts implement live or plausible workflows, but repeat a lot
of SINF, account-reference, demographic-code, and StudentTracker row-building
logic:

- `01-process.R`
- `01m-process_foster_request.R`
- `01n-process_migrant_request.R`
- `01s-process_seal_biliteracy.R`
- `01g-processAlvord.R`
- `01p-process_selpa_request.R`
- `01u-processMVUSD.R`
- `01v-process_tvusd_request.py`

Suggested direction: extract shared helpers for SINF loading, account enrichment,
StudentTracker row formatting, trailer/header writing, blocker writing, and
demographic drift checks. This is refactoring work, not deletion.

For Fall 2026, the cleaner shape would be a manifest-driven process with at
least two request cohort classes:

- `standard`: recurring annual cohorts such as countywide AVID, Foster, Migrant,
  and other configured countywide/program files.
- `ad_hoc`: district/project requests such as TVUSD, MVUSD CTE, SELPA variants,
  or other source-list-driven files.

## Generated Outputs And Runtime State

These directories/files look like outputs or runtime artifacts, not source.
They may be valuable for audit/reproduction, but should have a retention rule
instead of being treated as active code.

| Path | Notes |
|---|---|
| `downloads/` | NSC downloaded returns plus manifests; 2.8 GB. |
| `processed/` | Expanded, renamed, and sorted report outputs; 4.4 GB. |
| `requestfiles/` | Generated request upload files and test files. |
| `submissionfiles/` | Generated annual upload files and test files. |
| `full_detail/` | Generated detail extracts from `11-Detail.R`. |
| `audit/` | Generated request blocker and summary files. |
| `state/` | Runtime upload/download state; useful for reruns, not source logic. |
| `migrant_workflow/parsed/` | Generated parsed migrant BASIC CSVs. |
| `migrant_workflow/output/` | Generated migrant workbook output. |
| `county_grad_w_accounts.rds` | Generated by `01-process.R`; only the legacy `01d-processAVID.R` reads it directly. |
| `county_cohort_summary.csv`, `service_account_analysis.csv`, `migrant_request_summary.csv`, `migrant_service_account_analysis.csv`, `selpa_request_summary.csv`, `selpa_request_blockers.csv`, `migrant_missing_names.csv` | Generated summary/audit files. |
| `class_2024_nsc_detail.csv`, `grad_headers.csv`, `prev_avid_headers.csv` | Appears to be ad-hoc inspection or prior-output artifacts; verify before removing. |

## Data Inputs To Treat Carefully

These may look old or bulky but are source/reference material for current or
potential reruns.

| Path | Notes |
|---|---|
| `data/SINF/` | Large at about 2.2 GB, but source for `REQ-02` SINF rebuilds. Do not delete unless `data/cumulative_sinf.parquet` and `data/sinf_merge.parquet` become the only retained sources by policy. |
| `data/*_152_account.parquet`, `data/ClassOf*-152_cohort_outcomes.parquet`, `data/CHRT_*.csv` | Official/cohort inputs used by annual and request generators; not cruft without a year-specific retention decision. |
| `data/AccountRefs/` | Raw downloaded account-reference sheets; likely superseded by `data/account_refs.xlsx`, but useful as provenance. Archive rather than delete if provenance matters. |
| `data/_needsSINF/` | Looks like a held-aside charter source needing SINF/account reconciliation. Review before deletion. |
| `data/cumulative_sinf.parquet`, `data/sinf_merge.parquet` | Generated support files, but active pipeline inputs. Keep or regenerate deliberately. |
| `data/rccd_*` | RCCD consolidated matching inputs/outputs. Used by `11-Detail.R` or `rccd/` helpers; do not remove without replacing the RCCD workflow. |

## Suggested Cleanup Sequence

1. Add ignore rules for `.DS_Store`, `.RData`, and `.Rhistory`.
2. Delete local/editor/runtime caches: `.DS_Store`, `.RData`, `.Rhistory`, `.Rproj.user/`, `__pycache__/`.
3. Retire `main.py` and `03-watermark.py`.
4. Modernize standard annual request workflows, especially countywide AVID,
   Foster, Migrant, and other configured recurring cohorts.
5. Decide whether to archive or delete superseded ad-hoc workflows:
   `01t-processTVUSD.R` and `data/TVUSD Postsecondary Students 2023.24.xlsx`.
6. Set a retention rule for `downloads/`, `processed/`, `requestfiles/`,
   `submissionfiles/`, `full_detail/`, and generated root summary files.
7. Refactor repeated active generators only after the spec gaps most likely to
   change behavior are addressed.
