# Decisions - StudentTracker GradFile

The "why" layer. Anything a future maintainer (human or agent) would otherwise
have to rediscover the hard way. Entries are append-mostly; superseded
decisions get a `Superseded by` line, never deleted.

---

### DEC-01 - Dated Output Names
- **Decision:** Outbound files and several audit outputs use the run date in `YYYYMMDD` form in filenames and header transmission dates.
- **Because:** The StudentTracker file contract includes a transmission date, and the runbook describes dated outputs as the operator-facing convention.
- **Confirmed by:** code and runbook on 2026-06-12 extraction pass
- **Affects:** REQ-04, REQ-05
- **Revisit if:** reruns need deterministic, source-date-based names instead of operator-run-date names.

### DEC-02 - Stateful Transfers
- **Decision:** Upload and download helpers write JSON state under `state/` and skip terminal states by default.
- **Because:** SFTP work can be rerun, and state prevents successful accounts/files from being resent or refetched accidentally unless `force = TRUE` is used.
- **Confirmed by:** code on 2026-06-12 extraction pass
- **Affects:** REQ-09, REQ-10, REQ-11
- **Revisit if:** the process moves to a queue/orchestrator with authoritative transfer state.

### DEC-03 - Detail CSV Isolation
- **Decision:** Returned DETAIL CSVs are moved into `processed/<date>/<district>/detail` and excluded from renamed report ZIPs. When a processing suffix identifies a student group, the same suffix is included in the ZIP filename.
- **Because:** The code comment identifies this as PII isolation, keeping row-level detail separate from shareable report bundles. Carrying the suffix into the ZIP name prevents AP, dual-enrollment, IB, SSB, or other parallel group bundles from becoming ambiguous after they leave their parent folders.
- **Confirmed by:** `02-upload.py:1361` on 2026-06-12 extraction pass
- **Affects:** REQ-12
- **Revisit if:** downstream delivery requires detail files inside the same package as aggregate reports.

### DEC-04 - RCCD Consolidated Parquet
- **Decision:** RCCD enrollment enrichment flows through one consolidated `data/rccd_matched_ssid.parquet` with stable College Student ID to SSID matching.
- **Because:** The RCCD integration plan says `11-Detail.R` should consume one consolidated parquet across all term folders, using this repo's SINF source and crosswalk persistence.
- **Confirmed by:** `docs/RCCD_MultiTerm_Integration_Plan.md` on 2026-06-12 extraction pass
- **Affects:** REQ-16
- **Revisit if:** RCCD starts providing SSIDs directly in all source terms or the matching authority moves outside this repo.

### DEC-05 - District-Specific Source Bounds
- **Decision:** District-provided custom cohorts, including TVUSD and MVUSD, remain bounded to the source file and service account for that district.
- **Because:** The code hard-codes the district/account constants, and the prior TVUSD run was validated by source-ID overlap rather than raw return row count.
- **Confirmed by:** code and prior rollout memory on 2026-06-12 extraction pass
- **Affects:** REQ-07, REQ-08
- **Revisit if:** a district asks RCOE to widen a custom cohort from provided IDs to all local graduates.

### DEC-06 - Missing Required Request Fields Are Blockers
- **Decision:** Custom request rows missing core StudentTracker-required fields are audited as blockers and withheld from request bodies.
- **Because:** `docs/submission_guidance.md` states that SELPA source files are not assumed request-ready and missing mandatory fields are stoppers.
- **Confirmed by:** local docs and code on 2026-06-12 extraction pass
- **Affects:** REQ-05, REQ-06
- **Revisit if:** NSC accepts a documented partial-field request type or the source owner explicitly accepts partial rows.
- **Superseded by:** DEC-18 for SELPA run-level behavior.

### DEC-07 - Migrant BASIC Means Districtwide BASIC
- **Decision:** Migrant BASIC extraction copies only internal BASIC reports where the ACT token equals the service-account token.
- **Because:** The runbook states this ignores school-level BASIC exports and keeps only districtwide reports for downstream workbook building.
- **Confirmed by:** README and code on 2026-06-12 extraction pass
- **Affects:** REQ-14, REQ-15
- **Revisit if:** school-level migrant reports become part of the workbook deliverable.

### DEC-08 - Comprehensive Return Selection
- **Decision:** `expand_and_rename()` defaults to selecting the latest comprehensive DETAIL file and ZIP bundle by RUNDT/job matching before copying to `processed/`.
- **Because:** The runbook notes that multiple batches can coexist in a download folder and that EFFDT/RUNDT tags prevent collisions.
- **Confirmed by:** README and code on 2026-06-12 extraction pass
- **Affects:** REQ-12, REQ-13
- **Revisit if:** every run is downloaded into an already-isolated folder with exactly one batch.

### DEC-09 - No Local Business Rules Registry
- **Decision:** This extraction does not cite `BR-NN` requirements, and StudentTracker/CALPADS business rules stay local to this repo for now.
- **Because:** No `rules.md` registry was found in the project root or near project docs during the extraction pass, and the owner confirmed the rules should remain local rather than being promoted during this pass.
- **Confirmed by:** local file inventory and Project maintainer on 2026-06-12 extraction interview
- **Affects:** all requirements
- **Revisit if:** a central RCOE/dbt business rules registry is selected for StudentTracker work.

### DEC-10 - Demographic Drift Is A Stopper
- **Decision:** Silent blank demographic outputs caused by source-format changes are unacceptable; demographic drift should stop the outbound run before upload.
- **Because:** The project has already experienced a demographic source-format change that failed silently and caused downstream NSC demographics reports to come back blank. The likely escalation path is districts questioning generated NSC reports or the College-Career Readiness unit noticing discrepancies from programmatic expertise.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-17
- **Revisit if:** NSC provides machine-readable validation that catches blank demographic reports before district-facing delivery.

### DEC-11 - Annual Submissions Are Not Request Files
- **Decision:** Annual submission files and ad-hoc request files must remain separate variants even though their row-building logic overlaps.
- **Because:** Annual submissions are standardized across all LEAs and based on official end-of-year 15.2 graduate reporting. Request files are ad-hoc cohorts, usually subsets of 15.2 graduates, sometimes newly identified students, and occasionally non-graduates when they are the subject of interest. The upload files use different headers and leading row semantics.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-04, REQ-05
- **Revisit if:** NSC collapses annual submissions and request files into one upload layout or one reporting contract.

### DEC-12 - NSC Downloads Are Unlabeled
- **Decision:** Downloaded NSC files cannot be trusted to identify whether they belong to annual whole-school/district outcomes or to a specific request file without post-download inference.
- **Because:** NSC downloads do not carry a reliable differentiator for the project variant. Matching reports to sent batches requires inspecting results and inferring from counts, student overlap, and whether the output size looks like an annualized school/district outcome or an ad-hoc request cohort.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-13
- **Revisit if:** NSC adds stable request/submission identifiers to downloaded filenames or report metadata.

### DEC-13 - Exclude LEAs Without Service Accounts Or Graduates
- **Decision:** Perris Elementary, Romoland, and Menifee are hard-excluded from countywide annual StudentTracker submissions because they do not have StudentTracker service accounts and do not have graduates.
- **Because:** These LEAs should not appear in graduate submissions; if rows appear anyway, they are upstream noise rather than routable submission records.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-01
- **Revisit if:** one of these LEAs receives a StudentTracker service account or starts producing in-scope graduates.

### DEC-14 - CHRT Inputs Are Supported For Permitted Charters
- **Decision:** `data/CHRT.*` files should remain a supported annual 15.2 input path for charter LEAs where RCOE has permissions.
- **Because:** Missing CHRT coverage for an expected charter in a given year may represent missing source data, not an intentionally empty cohort. There should be data for each charter LEA for whom RCOE has permissions.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-01, REQ-18
- **Revisit if:** all permitted charter 15.2 data becomes reliably available in the countywide parquet.

### DEC-15 - Charter SINF Codes Use School Code
- **Decision:** The SINF join must account for charter records whose SINF `DistrictCode` value is the charter school code rather than the ordinary district code.
- **Because:** For charters, district code can equal school code in the SINF dataset, so joining only on cohort district code plus SSID can miss names. The `join_code` mapping is intentional for SINF matching.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-19
- **Revisit if:** future SINF extracts normalize charter records to ordinary district codes.

### DEC-16 - Charter CDS Variants Need Normalization
- **Decision:** Charter CDS values may need normalization before account-reference joins because sources encode the same charter CDS in more than one form.
- **Because:** Some sources present charter CDS as duplicated seven-digit school code plus seven-digit school code, while others present authorizer district code plus school code. These encodings refer to the same charter entity for account matching.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-03, REQ-20
- **Revisit if:** source systems and `data/account_refs.xlsx` converge on one canonical CDS encoding for charters.

### DEC-17 - Suppress RCOE-Bundled Independent Charters Until NSC Fixes Accounts
- **Decision:** Independent charter rows currently bundled under RCOE's NSC account are suppressed from RCOE district submission data.
- **Because:** Those charters should be independent LEAs in NSC, but they are temporarily bundled into the RCOE account. Suppression prevents their outcomes from being included in RCOE district data while the account setup remains wrong. During this workaround, the only charter that should remain in `data/account_refs.xlsx` is CBK / Come Back Kids.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-21
- **Owner:** Project maintainer owns the NSC account-remediation follow-up.
- **Revisit if:** NSC moves the affected charters to independent LEA accounts or provides a different official account mapping.

### DEC-18 - SELPA Requests Are Best Effort
- **Decision:** SELPA request generation should default to best-effort output: exclude blocked rows, write the blocker audit, and proceed with request-ready rows.
- **Because:** SELPA is a best-effort submission. If required fields cannot be derived for some students, those students are omitted rather than blocking usable rows.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-06
- **Revisit if:** SELPA or NSC requires all-or-nothing request submission for this cohort.

### DEC-19 - Do Not Add Underscores To Outbound SSIDs
- **Decision:** Outbound StudentTracker files send raw SSIDs without locally-added underscores. In the sharing copy, the annual, historical AVID, Alvord, TVUSD, and MVUSD generators serialize SSIDs as character values, preserving leading zeroes (2026-11-10).
- **Because:** Downstream reports may return identifiers with underscores, but local generators should not add them. Return-file matching should normalize returned identifiers instead of preserving the local underscore artifact.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-05, REQ-16, REQ-22
- **Revisit if:** NSC provides written guidance requiring requester-added underscore sentinels in outbound identifiers.

### DEC-20 - Sanitize Transfer Error Reporting
- **Decision:** SFTP upload/download/archive errors should be reported and stored by class/status only, not as raw exception strings.
- **Because:** Raw transfer exceptions can expose credentials, connection strings, or sensitive vendor/server details in logs or state files.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-11, REQ-11A
- **Revisit if:** transfer helpers use a logging framework that redacts sensitive fields by construction.

### DEC-21 - Receive Fallback Must Be Credential-Scoped
- **Decision:** Receive-directory fallbacks should use the current credential user, not the hard-coded `exampleuser` home path.
- **Because:** The hard-coded `/Home/exampleuser/receive` fallback appears to be a mistake and could route checks/downloads through the wrong account context.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-11
- **Revisit if:** NSC documents a shared receive home that is intentionally valid for all accounts.

- **Sharing-copy implementation (2026-11-10):** Download fallbacks use the current login via `_receive_target_dirs(user)`. The hard-coded home-directory fallback was removed.

### DEC-22 - Scaffold Thresholds Are Agentic Heuristics
- **Decision:** Report-scaffold overlap thresholds are implementation heuristics and should remain configurable conservative defaults rather than business requirements.
- **Because:** The current thresholds were generated agentically and do not reflect a human-approved statistical or policy standard. The durable rule is that uncertain matches stay `UNKNOWN` for review instead of being force-labeled.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-13
- **Revisit if:** repeated production batches establish validated threshold performance or NSC adds stable batch identifiers.

### DEC-23 - Migrant Workbook Title Must Reflect Scope
- **Decision:** The migrant workbook title should be dynamic or otherwise reflect the actual workbook scope, not be hard-coded to Coachella Valley Unified School District.
- **Because:** The hard-coded Coachella Valley title appears to be a mistake and can mislabel multi-district or non-Coachella outputs.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-15
- **Revisit if:** the workbook is intentionally narrowed to a Coachella-only deliverable.

### DEC-24 - Standalone Watermark Script Is Not Authoritative
- **Decision:** Watermarking returned PDFs should be controlled by the report-processing workflow, using an above-content `pypdf` overlay sized to each visible page, not by a standalone script with a hard-coded directory, hard-coded AVID label, and duplicate invocation.
- **Because:** The standalone `03-watermark.py` main block appears to be a mistake. The maintained workflow already exposes optional watermarking through `expand_and_rename(..., header_text=...)`. Rendered CCR QA on 2026-08-28 also showed that the former `PyPDF2` merge could place longer text beneath opaque vendor content, leaving only the uncovered tail visible.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-23
- **Revisit if:** operators need a supported standalone watermark utility with explicit CLI arguments and idempotence checks.

### DEC-25 - Vendor Duplicate Corrections Belong In Data
- **Decision:** NSC DETAIL duplicate-removal exceptions should be maintained in a data file rather than embedded as hard-coded student/name pairs in `11-Detail.R`.
- **Sharing implementation (2026-11-10):** `11-Detail.R` reads `data/nsc_duplicate_corrections.csv` with character `SSID` and `Last_Name` columns. The shared template has zero rows; production correction pairs must remain private. See REQ-31 and DEC-41.
- **Because:** The exceptions are data corrections, and hiding them in script logic makes them harder to review, update, and audit across runs.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-16
- **Revisit if:** the vendor stops returning the duplicate rows or the corrections move into an upstream validated source.

### DEC-26 - Detail College Code Lists Need Annual Review
- **Decision:** The CSU, UCR, and RCCD college-code lists in `11-Detail.R` can remain in code for now, but they must be reviewed annually before specialized detail outputs are finalized.
- **Because:** The current lists are authoritative and current, but college-code membership can drift over time and stale lists would silently misclassify specialized outputs.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-16
- **Revisit if:** the lists become shared across projects, change frequently, or need non-code-owner updates.

### DEC-27 - Source Lists Define Request Cohorts
- **Decision:** For ad-hoc request files, students listed by the source owner should be requested when they pass required-field and account blockers, even if they are not regular high-school graduates in the 15.2 cohort.
- **Because:** Request files are custom-cohort submissions. The source list is the evidence that the student is in scope; 15.2 regular-graduate eligibility governs annual submissions, not every request-file use case.
- **Confirmed by:** Project maintainer on 2026-06-12 extraction interview
- **Affects:** REQ-05, REQ-06, REQ-07
- **Revisit if:** NSC changes request-file eligibility guidance or RCOE adopts an approval workflow for non-graduate request cohorts.

### DEC-28 - Project Dates Roll Forward Annually
- **Decision:** Cohort years, graduation windows, and source-file names are annual project parameters, not permanent constants.
- **Because:** This project recurs by copying a prior annual folder forward. Older dates and data may remain in the copied folder, so fixed dates like `2024-09-01` through `2025-08-31` are evidence from the current run, not durable requirements for future years.
- **Confirmed by:** Project maintainer on 2026-06-12 refinement
- **Affects:** REQ-01, REQ-24, REQ-25
- **Revisit if:** the workflow moves to a parameterized pipeline that cannot accidentally retain prior-year dates.

### DEC-29 - Request Files Split Into Standard And Ad-Hoc Cohorts
- **Decision:** Request-file workflows should distinguish standard annual request cohorts from district/project-request cohorts.
- **Because:** Countywide AVID, Foster, Migrant, and similar recurring program cohorts are expected parts of the annual process, while district/project requests are initiated by a specific local need or source list. Treating all request generators as one-off scripts obscures which files belong in the annual workflow and which should be cleaned up after a project-specific run.
- **Confirmed by:** Project maintainer on 2026-06-12 refinement
- **Affects:** REQ-05, REQ-07, REQ-24, REQ-25
- **Revisit if:** all request cohorts are moved into a single manifest-driven generator with explicit `standard` versus `ad_hoc` cohort types.

### DEC-30 - Preserve This Folder Until Fall 2026 Copy
- **Decision:** The current project folder should remain intact; cleanup and refactoring should happen in the Fall 2026 copied folder when it is time to generate the next annual files.
- **Because:** This folder represents the current source state and working history. It will be copied forward for Fall 2026, and that copied state is the appropriate place to cull older data, remove stale one-off scripts, and refactor the workflow.
- **Confirmed by:** Project maintainer on 2026-06-12 refinement
- **Affects:** REQ-25
- **Revisit if:** this folder becomes the active Fall 2026 workspace instead of being copied.

### DEC-31 - CCR Deduplication Is Program-Scoped
- **Decision:** For the four-class summer CCR request cycle, collapse repeated SSIDs only within the same AP, CC, IB, or SSB family, keeping the latest listed class record; preserve the same student across different program families.
- **Because:** Repeated source rows should not create duplicate D3 records in one StudentTracker batch, while membership in multiple CCR groups represents distinct requested analyses.
- **Affects:** REQ-05, REQ-24, REQ-26
- **Revisit if:** StudentTracker supplies a batch contract that supports repeated identifiers within one request family or the source owner changes the meaning of cross-class duplicates.

### DEC-32 - Authentication Failures Are Run Stoppers
- **Decision:** An SFTP upload or download run stops immediately after its first authentication failure instead of continuing to try the remaining district credentials.
- **Because:** A location block or credential-policy event can affect many accounts at once, and repeated automated failures may trigger or deepen a vendor lockout. Stopping after one failure limits account risk and gives the operator a clear point to check VPN/location and password state.
- **Confirmed by:** Project maintainer on 2026-08-25
- **Affects:** REQ-09, REQ-11, REQ-11A, REQ-11B
- **Revisit if:** NSC documents that failed logins are isolated per account and cannot contribute to shared location or rate-limit controls.

### DEC-33 - Countywide AVID Combines Same-Year Course/Graduate Intersections
- **Decision:** Build each AVID class by intersecting CALPADS 3.11 State Course `9211` participants with regular graduates in that same reporting year's 15.2 Account cohort, then combine Classes 2022 through 2025 into the default countywide request batch and route them through current account references.
- **Because:** The 20260825 AVID batch used only the 2024-25 source pair and therefore requested only Class 2025. Read-only MinIO inventory confirms complete 3.11/15.2 annual source pairs for Classes 2022, 2023, 2024, and 2025. Pairing within each year preserves the valid AVID-course/graduate intersection while the combined request satisfies the multi-class request rule. Class 2026 remains opt-in because it was not part of the completed historical results cycle.
- **Confirmed by:** Project maintainer on 2026-08-24 and refined on 2026-09-03 after source inventory
- **Affects:** REQ-03, REQ-05, REQ-06, REQ-17, REQ-22, REQ-24, REQ-29
- **Revisit if:** the AVID program owner changes the cohort definition, the desired historical span, or the inclusion timing for newly graduated classes.

### DEC-34 - Outbound Optional Name Nulls Are Empty Fields
- **Decision:** The AVID request generator normalizes missing middle names and suffixes, including common textual placeholders, to empty tab fields and validates the serialized files before they can enter an upload manifest.
- **Because:** R missing values remained `NA` through normalization and were converted to literal `NA` text when the new generator assembled rows with `paste()`. The older `readr::write_delim(..., na = "")` path had blanked those values automatically.
- **Confirmed by:** Project maintainer on 2026-08-25 after NSC intake feedback
- **Affects:** REQ-05, REQ-24
- **Revisit if:** NSC publishes a different explicit representation for absent optional name fields.

### DEC-35 - AVID Account Mappings Refresh From The Current Workbook
- **Decision:** The countywide AVID generator joins every selected graduate to the current `data/account_refs.xlsx` by CDS and uses that workbook's SA, ACT, district, and high-school values for outbound routing.
- **Because:** `county_grad_w_accounts.rds` caches account mappings. An operator correction to the maintained workbook, such as Beaumont Middle College High changing from `A30451` to `055457`, would otherwise not reach regenerated request files unless the entire cohort RDS were rebuilt first.
- **Confirmed by:** Project maintainer on 2026-08-25 after updating the Beaumont mapping
- **Affects:** REQ-03, REQ-06, REQ-24
- **Revisit if:** the cohort artifact is replaced by a manifest that cryptographically binds the exact account-reference workbook used to build it.

### DEC-36 - NSC Service-Agreement Acceptance Governs Account ACT Codes
- **Decision:** Treat a six-character ACT value in the maintained account reference as request-valid when NSC intake evidence shows that the account/file was accepted with that value, even if the value is not present in ACT's public institutional-code directory.
- **Because:** NSC rejected San Jacinto AVID file `20260824_90000004_sanjacintounifiedschooldistrict_avid-20260825005506.txt` only for literal `NA` middle-name and suffix fields; it did not reject the file's `A30452` value for San Jacinto Middle College High. Public-directory absence is therefore a review signal, not sufficient evidence that the code is invalid under the NSC service agreement.
- **Confirmed by:** Project maintainer on 2026-08-25 from the NSC rejection notice
- **Affects:** REQ-03, REQ-06, REQ-24
- **Revisit if:** NSC rejects `A30452`, removes it from service account `90000004`, or issues a replacement code.

### DEC-37 - Multi-Class CTE Uses CALPADS-Filtered Annual 15.2 Cohorts
- **Decision:** The countywide CTE request defaults to Classes 2023 through 2025 and uses each year's CALPADS 15.2 Account extract produced with the native `CTE Completer = Y` filter. The three classes are combined into one CTE request per service account while retaining each student's graduation date and cohort year in the audit lineage.
- **Because:** The prior reconstruction intersected four 3.20 snapshots with only Class-of-2025 graduates. The annual filtered 15.2 objects directly identify the requested CTE-completer graduate population and are available for Classes 2023, 2024, 2025, and 2026. For Class 2025, the CALPADS-filtered source contained 183 regular graduates absent from the reconstructed cohort and excluded 20 reconstructed candidates, so the two methods are not interchangeable. Class 2026 remains opt-in because postsecondary results for the newly graduated class were not part of the completed-results cycle.
- **Confirmed by:** Project maintainer on 2026-09-03 and read-only MinIO inventory/reconciliation of the annual countywide CTE objects
- **Affects:** REQ-03, REQ-05, REQ-24, REQ-27
- **Revisit if:** CALPADS changes the 15.2 `CTE Completer` filter, the program owner chooses a different class-year span, or mature Class-of-2026 StudentTracker outcomes are intentionally added.

### DEC-38 - CTE Returns Stay Manifest-Scoped And Visibly Labeled
- **Decision:** CTE returns are staged from an exact DETAIL/ZIP manifest, processed with suffix `_CTE`, and watermarked `CTE STUDENTTRACKER REPORT - THIS REPORT IS ONLY FOR CTE COMPLETERS` before reports-only ZIP packaging.
- **Because:** AVID and CTE returns can coexist under the same service account, EFFDT, and RUNDT, while NSC ZIP filenames omit the request-family label. Exact roster and job pairing prevents a same-day AVID bundle from being mislabeled as CTE; the suffix and visible header preserve scope after distribution.
- **Confirmed by:** Project maintainer on 2026-08-28 and exact roster reconciliation of the 21 CTE DETAIL returns
- **Affects:** REQ-12, REQ-13, REQ-23, REQ-28
- **Revisit if:** NSC adds a stable request-family token to returned filenames or report metadata.

### DEC-39 - Request Class Span Correction
- **Decision:** Request files may cover a single class. Remove the mistaken universal multi-class/consecutive-class guard from shared request validation. Annual graduate submissions remain single-class; established historical program defaults remain as configured.
- **Because:** The prior decision incorrectly generalized historical request scope into a file-type requirement and incorrectly attributed that rule to the user. The user corrected it during the SMART request on 2026-10-28.
- **Confirmed by:** Project maintainer on 2026-10-28
- **Affects:** REQ-05, REQ-09, REQ-24, REQ-29

### DEC-40 - SMART Source Scope And Exclusion
- **Decision:** Build one Class 2025 SMART request for Rancho Mirage High under Palm Springs Unified SA 90000005. Interpret workbook IDs as district LocalIDs, resolve SSIDs through local cohort data, and apply reviewed local exclusions before serialization.
- **Because:** Source-list identifiers must resolve within the intended district/class; documented exclusions remain local input and missing attendance dates must not be invented.
- **Confirmed by:** Project maintainer on 2026-10-28
- **Affects:** REQ-03, REQ-05, REQ-06, REQ-07, REQ-30

### DEC-41 - Sharing Package Uses Explicit File Selection
- **Decision:** Create the 2026-11-10 sharing copy from an explicit source/document allowlist. Rebuild reference templates without operational rows or original binary metadata.
- **Because:** Student identifiers can appear in source code as well as datasets, and broad folder copies also retain credentials, caches, reports, and session history.
- **Affects:** REQ-16, REQ-31, DEC-25. The sharing copy externalizes DETAIL correction pairs into a header-only local CSV.
- **Scope:** This is a sanitized code reference, not an annual rollover or an operational dataset. Original cohort dates and public district/school codes remain for context.

### DEC-42 - School Crosswalk And Transfer Credentials Have Separate Contracts
- **Decision:** Preserve the original header-only `Refs`, `NCES`, and `CDS` workbook structure and document school-level mappings separately from SFTP credential rows. Refs.SA routes accounts; Refs.ACT identifies the school within the account; Refs.CDS connects source students to that mapping.
- **Because:** An SA can cover many schools, and an SFTP username is not the SA. Flattening the reference to one row per SA loses school routing and returned-report labels.
- **Report naming:** Friendly report names preserve district/school-or-districtwide scope, type, verified program suffix, and vendor date tags. DETAIL stays separate. Foreign SA tokens and conflicting school labels are rejected. Hash equality, not file size alone, controls collision deduplication.
- **Provenance (maintainer clarification, 2026-11-10):** The workbook combines multiple NSC files and may include local adjustments. Treat it as a maintained composite crosswalk rather than an untouched vendor export. Exact source versions, assembly steps, and possible adjustments remain undocumented (Q-18). NCES/CDE files are present locally, but their role in workbook assembly is not confirmed.
- **Maintenance:** Retain source-file/date references and record applied adjustments and reasons when updating the crosswalk; reconcile a new export against the maintained mappings before replacement.
- **Affects:** REQ-03, REQ-12, REQ-32

### DEC-43 - Annual Configuration And Explicit Charter Gap
- **Decision:** Centralize annual class, source path, date window, header school year, run date, and excluded districts. Preserve Class 2025 defaults until a new class is explicitly selected. Reject detected CHRT inputs before outputs rather than reading and discarding them.
- **Because:** The existing CHRT-to-parquet overwrite loses input records. A reviewed field crosswalk and permitted-charter list are needed before combining official sources safely; do not fabricate either.
- **Affects:** REQ-01, REQ-18, REQ-25

### DEC-44 - Migrant Titles Reflect Participating Scope
- **Decision:** Derive a single-district title from the parsed district labels, label multi-district output as Participating Districts, and allow an explicit nonblank `--title` override. Reject an empty default scope.
- **Because:** A hard-coded district title mislabels a combined workbook, while “countywide” could overstate coverage when some districts are absent.
- **Affects:** REQ-15, DEC-23

### DEC-45 - Public Release Uses Synthetic Routing And Untracked Local Inputs
- **Decision:** Replace operational SA constants, historical login references, and the internal bucket name with example values before publishing. Preserve code relationships and public school/district codes.
- **Decision:** Track input templates under `templates/`, never the live credential or account-reference paths. `prepare_local_templates.py` creates ignored local files without overwriting an existing input.
- **Because:** An account identifier is not a password, but it is unnecessary public operational detail. Tracking a header-only live credential path would also track later edits containing real credentials.
- **Affects:** REQ-31, REQ-32, REQ-33
