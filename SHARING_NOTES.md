# Sharing notes — November 10, 2026

This folder is a sanitized code reference prepared from the StudentTracker GradFile project. It contains no original student data files, report outputs, or working credentials. Share this folder or the accompanying dated ZIP, not the original operational folder.

## Included

- Python and R source, RCCD utilities, existing synthetic tests, requirements, decisions, and runbooks.
- Script comments identifying purpose, important scope rules, execution behavior, and retained historical assumptions.
- A freshly generated `templates/data/account_refs.xlsx` reproducing the original `Refs` (10 columns), `NCES` (5 columns), and `CDS` (11 columns) worksheet headers. All three sheets contain zero data rows, no hidden sheets, and no original workbook metadata.
- Header-only `templates/creds.csv` and `templates/data/nsc_duplicate_corrections.csv`. Run `prepare_local_templates.py` to create their ignored live paths; existing files are never overwritten.
- `examples/` with source-list, SINF, and account-reference CSV headers, plus two explicitly synthetic student examples. The invented identifiers and dates are illustrative and are not approved submission records.
- Empty operational directories showing where locally supplied inputs and generated outputs belong.
- `SHARE_MANIFEST.csv` with package file sizes and SHA-256 hashes, excluding the manifest itself.

## Excluded

All original contents of `data/`, `downloads/`, `processed/`, `full_detail/`, `requestfiles/`, `submissionfiles/`, `audit/`, `state/`, and the migrant workflow data/output folders were excluded. The templates and examples above were created separately.

Root CSV extracts and summaries, RDS/parquet files, Excel source workbooks, PDFs, archives, `CALPADScfsforms.xlsx`, working credentials, credential backups, saved R sessions/history, `.Rproj.user`, virtual environments, Python caches, Git history, machine metadata, and scratch/output artifacts were excluded. Local agent instructions and credential configuration were not copied.

Public district/school names, school/district codes, original cohort years, and generic storage-path conventions remain as implementation context. Operational service-account constants, historical login references, and the internal bucket name have been replaced with examples for this public release. Personal staff attribution was replaced with “Project maintainer.”

## Code changes

The original `11-Detail.R` contained student identifiers paired with surnames as vendor duplicate corrections. Those literals were removed. The shared version loads correction pairs from `data/nsc_duplicate_corrections.csv` and matches on both `SSID` and `Last_Name`. The supplied header-only file removes no students. Keep any real correction list local to an authorized operational copy.

This change implements the existing REQ-16 / DEC-25 direction. REQ-31 and DEC-41 document the sharing package. The sharing copy also implements REQ-22 / DEC-19 by removing locally added SSID underscores from the annual, historical AVID, Alvord, TVUSD, and MVUSD generators. These fields are serialized as character values to preserve leading zeroes. Additional sharing-copy corrections are listed below. The original project files were left unchanged.

Additional corrections reconcile the existing specification with the shared code:

- Annual settings are centralized in `annual_submission_config.R`, the CDS account join is explicit, and all three required district exclusions are applied.
- Detected CHRT inputs now stop the annual generator rather than being silently discarded. Full CHRT ingestion and permitted-charter coverage verification remain pending reviewed inputs.
- Download fallback directories are scoped to the current login. Transfer/archive errors persist class information rather than raw vendor exception text.
- Report collision checks use size plus SHA-256. Different same-sized reports are retained; foreign SA tokens and conflicting SA/ACT school names are rejected.
- Migrant workbook titles reflect participating scope or an explicit override.
- Direct execution of the historical standalone watermark script is retired to prevent its old hard-coded double application.
- `docs/accounts_and_report_naming.md` documents source-reference structure and renaming. `docs/workflow_status.md` distinguishes supported entry points from historical scripts and records remaining gaps.

Comments explain charter SINF mapping, script responsibilities, and import-time reference loading. REQ-32 and DEC-42 through DEC-44 record the account/naming and reconciliation decisions. The maintainer clarified that the original workbook combines multiple NSC files and may contain local adjustments. Exact source versions, assembly steps, and possible adjustments remain undocumented; no original crosswalk rows were included in this package.

## Reading and testing the code

This is the public-release variant; see `PUBLIC_RELEASE_REVIEW.md` for additional replacements and the tracked-template boundary.

Run commands from this folder after running `python3 prepare_local_templates.py`. Python requires 3.13 or newer and the dependencies in `pyproject.toml`; use `uv sync` to create a local environment. R scripts list their package imports. `main.py` is a placeholder rather than the workflow entry point.

```sh
uv run python -m unittest discover -s tests -p 'test_*.py'
Rscript tests/test_avid_request_contract.R
Rscript tests/test_detail_corrections.R
Rscript tests/test_outbound_ssid_contract.R
Rscript tests/test_annual_submission_config.R
```

The Python PDF visual test additionally needs Pillow and the `pdftoppm` executable. Validation for this package used the existing local development environment. Importing `02-upload.py` reads the header-only credential CSV and account workbook; it does not start a transfer. The credential list is empty.

Pipeline execution requires privately supplied inputs and any appropriate access configuration. The synthetic CSV is illustrative, not a complete end-to-end fixture for every generator. `CALPADScfsforms.xlsx` and raw SINF exports must be supplied separately for scripts that reconstruct SINF headers.

Review project-specific cohort dates, source paths, service-account routing, and historical scripts before adapting the code. The runbook records original operational commands, including network reads and uploads; preparing this share copy did not execute those commands. This copy is not an annual rollover, and its output directories are intentionally empty.

## Validation

- All 39 Python unit tests passed using synthetic fixtures, including request contracts, class scope, mocked transfer authentication, ZIP naming, and PDF watermark rendering.
- All 21 Python files passed syntax checks. All 22 R files passed parsing.
- The annual configuration test exercised the actual cohort transformation with a fake parquet reader, a new class window, the three excluded districts, and the CHRT stop guard.
- Account/report integration tests cover friendly school/districtwide naming, date tags, reports-only ZIPs, DETAIL isolation, foreign accounts, ambiguous mappings, hash-based collision handling, sanitized errors, and migrant title scope.
- The outbound SSID contract test passed for all five updated generators, including tab-delimited serialization and preservation of leading zeroes.
- The R AVID request contract test passed. The new synthetic DETAIL correction test passed for an empty correction list, a nonmatching surname, and an exact ID/surname pair.
- The account workbook was visually reviewed and independently read back: three worksheets with the exact original header schemas and zero data rows. The credential and correction templates were confirmed header-only.
- Original embedded student correction identifiers and surnames were checked in memory against all package file payloads, including workbook XML; none remain. Remaining 10-digit literals are confined to explicitly synthetic examples/tests.
- The package was checked for symlinks, unexpected file types, personal machine paths, email addresses, private-key markers, and AWS access-key patterns. No matches remained. Public package-host URLs in `uv.lock` were retained.
- No operational pipeline, warehouse query, MinIO connection, or real SFTP transfer was run. Full end-to-end processing requires private inputs that are deliberately absent.
- Existing source files were compared against the selected source inventory; changes are confined to the new sharing folder. The archive was read back and compared with the file manifest.

Before sharing a modified copy, remove any newly supplied private inputs, generated student-level outputs, transfer state, and caches. The included `.gitignore` helps prevent accidental commits; it does not sanitize files or ZIP archives.
