# Supported entry points and remaining work

Reconciled for the sharing copy on 2026-11-10. This status supersedes current-state assumptions in the historical June cleanup audit. These scripts remain project-specific tools rather than a single orchestrated application.

| Workflow | Entry point | Status / configuration |
|---|---|---|
| Annual graduate submission | `01-process.R` | Uses `annual_submission_config.R`. Set `ST_COHORT_YEAR`, optionally `ST_COHORT_PATH` and `ST_RUN_DATE`. Defaults retain Class 2025. CHRT presence stops the run pending a reviewed input crosswalk. |
| Countywide AVID | `01x-process_avid_request.py` | Maintained Python generator; explicit run date/class selection and aggregate preflight. R implementation retained for its contract helpers/tests. |
| Summer CCR AP/CC/IB/SSB | `01w-process_ccr_summer_request.py` | Program-specific outputs and audits. Its four-class source layout remains tied to the original summer cycle. |
| Countywide CTE | `01y-process_cte_request.py` | Explicit class range, preflight, blocker/manifest output; defaults retain Classes 2023–2025. |
| Alvord AVID/IB/PUENTE | `01g-processAlvord.R` | District-specific multi-year workflow; review configured source lists before reuse. |
| TVUSD / MVUSD / SMART / SELPA | `01v-process_tvusd_request.py`, `01u-processMVUSD.R`, `01z-process_smart_request.py`, `01p-process_selpa_request.R` | Source-bounded project requests. Review their district, school, class, and source settings. |
| Foster / Migrant / Seal | `01m-process_foster_request.R`, `01n-process_migrant_request.R`, `01s-process_seal_biliteracy.R` | Recurring R workflows; annual configuration is still embedded in these scripts. |
| Transfers, report selection, rename, watermark, ZIP | `02-upload.py` helpers | Main block is inert. Read the runbook and `accounts_and_report_naming.md`; call helpers with explicit account/batch scope. |
| Migrant summary | `12-parse_migrant_basic_reports.R`, then `13-build_migrant_workbook.py` | Title follows participating districts; optional `--title` provides an explicit scope label. |
| Annual detailed enrichment | `11-Detail.R`, supported by `rccd/*.R` | Private local inputs and correction file required. Annual college-code review remains a manual responsibility. |
| Historical utilities | `01d-processAVID.R`, `01t-processTVUSD.R`, `03-watermark.py` | Retained for reference. Standalone watermark execution is retired; use maintained processing helpers. |
| Project scaffold | `main.py` | Placeholder, not a processing entry point. |

## Corrections made in the sharing copy

- Raw character SSIDs replace locally prefixed SSIDs in all five affected legacy generators (REQ-22).
- DETAIL duplicate-correction pairs are local CSV input rather than private source-code literals (REQ-16).
- The annual path, graduation window, header school year, filename/header run date, and all three district exclusions are configured consistently (REQ-01, REQ-25). The CDS account join is explicit.
- Annual CHRT files are no longer silently read and discarded. Their presence stops the annual run before output writes (REQ-18 remains incomplete).
- Download receive fallbacks use the current login. Upload/download/archive failure handling records exception classes, not vendor exception messages (REQ-11, REQ-11A).
- Report collisions compare content hashes; foreign-account report/DETAIL names and conflicting SA/ACT school mappings are rejected (REQ-03, REQ-12).
- Migrant titles use actual participating district labels or an explicit override (REQ-15).
- The header-only account template reproduces all three original worksheet schemas (REQ-32).

## Remaining limitations

**Charter input coverage (REQ-18):** The original requirement is clear, but the project does not provide a maintained registry of permitted charter LEAs or a reviewed CHRT-to-countywide field crosswalk. The annual generator now stops on detected CHRT files instead of discarding them. This is a guard against known data loss, not complete charter ingestion or coverage verification. A parquet-only run still needs an operator's coverage review.

**Demographic checks (REQ-17):** CCR and CTE have schema/all-blank protections, and AVID has identifier/source checks. The requirement is not uniformly enforced across the older R generators. Tests passing for the maintained generators do not establish coverage for every historical script.

**Account reference maintenance (REQ-03, REQ-21, REQ-32):** The schemas and runtime uses are documented. The maintainer confirms that the workbook combines multiple NSC files and may contain local adjustments. Exact source versions, assembly steps, and possible adjustments remain undocumented; nearby NCES/CDE files are not confirmed assembly inputs. Charter suppression policy and every CDS mapping are not automatically validated in all generators. Status/closure columns are metadata, not universal eligibility filters.

**Annual rollover (REQ-25):** The annual submission has centralized settings; legacy recurring request scripts and report-scaffold source globs still need their original dates reviewed. The sanitized package is not a complete new-year rollover.

**Detailed enrichment (REQ-16):** College-code list review has no persisted annual signoff. The synthetic correction test does not validate private NSC/RCCD matching data.

**Report processing (REQ-12, REQ-13):** The comprehensive selection heuristic can choose the wrong program if batches coexist. Exact roster/job selection is still required for program-specific delivery. Repeated optional PDF watermarking has no general idempotence guarantee. Treat `_Unknown`, `_ACT<code>`, and unchanged vendor-layout files as review items before distribution.

**Validation scope:** Tests use synthetic fixtures and mocked transfers. No production files, remote systems, or real credentials were used to validate the sharing-copy changes.
