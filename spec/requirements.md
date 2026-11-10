# Requirements - StudentTracker GradFile

| | |
|---|---|
| **Status** | REFINED - interview baseline; sharing-copy reconciliation |
| **Owner** | Project maintainer |
| **Last reviewed** | 2026-11-10 |
| **Source of record** | this file; runbooks and embedded docs are projections |

## Intent

This project produces National Student Clearinghouse StudentTracker graduate submissions, standard annual request files, ad-hoc district/project request files, returned-report processing outputs, migrant BASIC workbook summaries, and enriched annual detail extracts for Riverside County education workflows. The spec exists so future changes preserve cohort scope, file contracts, upload safety, and locally-sensitive detail handling across copied annual project folders.

## Requirements

### REQ-01 - Countywide Graduate Cohort
**WHEN** generating countywide annual submission files, **THE** countywide submission generator **SHALL** use `HSDiplomaGraduate` records from official end-of-year 15.2 inputs for the configured project year, excluding districts that have no StudentTracker service account and no graduates.
- **Acceptance:** A run of `01-process.R` reads official 15.2 cohort inputs and filters the output cohort to the configured graduation window for the project year.
- **Acceptance:** The graduation window is an annual project parameter and is not hard-coded to a prior year's dates when the project folder is copied forward.
- **Acceptance:** Records with `DistrictCode == "3367199"` (Perris Elementary), `DistrictCode == "3367231"` (Romoland), or `DistrictCode == "3367116"` (Menifee) do not appear in the generated countywide submission body.
- **Source:** `01-process.R:40`, `01-process.R:49`, `01-process.R:52`, `01-process.R:65`
- **Confidence:** [inferred]
- **Related:** DEC-13, DEC-14, DEC-28, Q-02

### REQ-02 - SINF Name Merge
**WHEN** rebuilding SINF support files, **THE** SINF preparation step **SHALL** read all caret-delimited files under `data/SINF`, apply CALPADS Student Information headers, retain the most recent row per `(DistrictCode, SSID)` by `ModifyDate`, and write `data/cumulative_sinf.parquet` plus `data/sinf_merge.parquet`.
- **Acceptance:** `data/cumulative_sinf.parquet` contains the distinct combined SINF rows with public-name headers.
- **Acceptance:** `data/sinf_merge.parquet` contains no more than one row per `(DistrictCode, SSID)`.
- **Source:** `01-process.R:68`, `01-process.R:82`, `01-process.R:95`, `01-process.R:100`, `01-process.R:113`, `01-process.R:119`
- **Confidence:** [verified]
- **Related:** Q-03

### REQ-03 - Account Enrichment
**WHEN** any submission or request generator prepares StudentTracker student rows, **THE** generator **SHALL** attach `SA`, `ACT`, district name, and high-school name from `data/account_refs.xlsx` before writing outbound rows.
- **Acceptance:** Generated outbound rows have the service-account token in the header and ACT/high-school values in the student body when the row is not blocked.
- **Acceptance:** Rows without required account data appear in a blocker, missing-name, unmatched, or summary output rather than being silently widened to another account.
- **Acceptance:** A six-character ACT value maintained in the account reference is not blocked solely because it is absent from ACT's public directory when NSC intake evidence confirms that the value is accepted under the service agreement.
- **Source:** `01-process.R:61`, `01-process.R:121`, `01p-process_selpa_request.R:100`, `01v-process_tvusd_request.py:134`, `01u-processMVUSD.R:97`
- **Confidence:** [verified]
- **Related:** DEC-16, DEC-36, Q-06

- **Sharing-copy clarification:** `Refs` is a school/CDS-to-account crosswalk, separate from transfer credentials. See REQ-32 and `docs/accounts_and_report_naming.md`.

### REQ-04 - Annual Submission File Contract
**WHEN** writing countywide annual submission files, **THE** countywide submission generator **SHALL** write tab-delimited `PH3` header rows, `PD3` student rows, and `PT3` trailer rows to `submissionfiles/YYYYMMDD_<SA>_<District>.txt`.
- **Acceptance:** The trailer count equals body row count plus 2.
- **Acceptance:** A test file is also written under `submissionfiles/test_file/` with no more than 800 sampled student rows.
- **Source:** `01-process.R:155`, `01-process.R:160`, `01-process.R:218`, `01-process.R:226`, `01-process.R:235`, `01-process.R:251`
- **Confidence:** [verified]
- **Related:** DEC-01, DEC-11

### REQ-05 - Request File Contract
**WHEN** writing a custom cohort request file, **THE** request generator **SHALL** write tab-delimited `H3` header rows, `D3` student rows, and `T3` trailer rows to `requestfiles/YYYYMMDD_<SA>_<District>[_<Batch>].txt`.
- **Acceptance:** The trailer count equals body row count plus 2.
- **Acceptance:** A test file is written under `requestfiles/test_file/` with no more than 800 sampled or first student rows.
- **Acceptance:** The request batch declares its intended source/cohort classes; single-class ad-hoc requests are allowed.
- **Acceptance:** A listed source student is eligible for request-file inclusion when required fields and account mapping pass blockers, even when the student is not a regular high-school graduate in the 15.2 cohort.
- **Source:** `docs/submission_guidance.md:23`, `docs/submission_guidance.md:37`, `docs/submission_guidance.md:105`, `01p-process_selpa_request.R:228`, `01p-process_selpa_request.R:250`, `01g-processAlvord.R:230`, `01g-processAlvord.R:249`, `01v-process_tvusd_request.py:210`, `01v-process_tvusd_request.py:253`
- **Confidence:** [inferred]
- **Related:** DEC-06, DEC-11, DEC-19, DEC-27, DEC-29

### REQ-06 - Request Blockers
**IF** a custom request source row is missing first name, last name, date of birth, last attendance date, service account, or ACT code, **THEN** the request generator **SHALL** write the row to an audit/blocker file and exclude it from the outbound request body.
- **Acceptance:** SELPA blockers are written to `selpa_request_blockers.csv`.
- **Acceptance:** SELPA request generation proceeds with non-blocked rows when at least one row is request-ready.
- **Acceptance:** TVUSD blockers are written to `audit/YYYYMMDD_tvusd_request_blockers.csv`.
- **Source:** `docs/submission_guidance.md:13`, `docs/submission_guidance.md:15`, `01p-process_selpa_request.R:132`, `01p-process_selpa_request.R:154`, `01p-process_selpa_request.R:160`, `01v-process_tvusd_request.py:176`, `01v-process_tvusd_request.py:192`, `01v-process_tvusd_request.py:206`
- **Confidence:** [verified]
- **Related:** DEC-06, DEC-18

### REQ-07 - Source-Bounded Custom Cohorts
**WHEN** generating a district- or program-specific request from a provided list, **THE** request generator **SHALL** limit body rows to source-list identifiers that match the intended local cohort and account mapping.
- **Acceptance:** TVUSD output is limited to `data/TVUSDClass2025.csv` SSIDs and `SA == "90000001"`.
- **Acceptance:** MVUSD output is limited to `data/MVUSD/CTE_SSID_MurrietaValleyUSD_ClassOf2025.csv` SSIDs, `DistrictCode == "3375200"`, `CohortYear == 2025`, and `SA == "90000002"`.
- **Source:** `01v-process_tvusd_request.py:10`, `01v-process_tvusd_request.py:147`, `01v-process_tvusd_request.py:207`, `01u-processMVUSD.R:61`, `01u-processMVUSD.R:85`, `01u-processMVUSD.R:90`, `01u-processMVUSD.R:103`
- **Confidence:** [verified]
- **Related:** DEC-05

### REQ-08 - Alvord Program Cohorts
**WHEN** generating Alvord AVID, IB, or PUENTE request files, **THE** Alvord generator **SHALL** combine CohortYear 2024 source-list SSIDs with CohortYear 2025 source-list SSIDs and filter all rows to Alvord CDS prefix `3366977`.
- **Acceptance:** The generated AVID, IB, and PUENTE requests contain only `substr(CDS, 1, 7) == "3366977"`.
- **Acceptance:** Output filenames include the group suffix `AVID`, `IB`, or `PUENTE`.
- **Source:** `README.md:11`, `README.md:27`, `01g-processAlvord.R:47`, `01g-processAlvord.R:107`, `01g-processAlvord.R:140`, `01g-processAlvord.R:144`, `01g-processAlvord.R:249`
- **Confidence:** [verified]
- **Related:** DEC-05

### REQ-09 - Upload Scoping And State
**WHEN** uploading request or submission files, **THE** upload helper **SHALL** validate the declared class span, select files by service-account token and optional filename prefix, skip terminal upload states unless `force = TRUE`, and support a `dry_run` mode that prints intended remote paths without transferring files.
- **Acceptance:** `upload_requests(..., request=True, cohort_years=[...], dry_run=True, filename_prefixes=[...])` does not call `sftp.put`.
- **Acceptance:** Request upload calls without any declared cohort years and graduate submission calls without exactly one declared cohort year stop before opening an SFTP connection.
- **Acceptance:** A previously successful upload is skipped unless `force = TRUE`.
- **Source:** `02-upload.py:318`, `02-upload.py:987`, `02-upload.py:996`, `02-upload.py:1007`, `02-upload.py:1023`, `02-upload.py:1036`
- **Confidence:** [verified]
- **Related:** DEC-02

### REQ-10 - Upload Verification
**WHEN** uploading a pending file, **THE** upload helper **SHALL** send it to `/Home/<user>/<filename>` and mark success only after the remote file size matches the local file size.
- **Acceptance:** Size mismatch records a failed state file and raises an upload error.
- **Acceptance:** Successful uploads write `state/uploads/<run_date>/<kind>/<user>__<filename>.json` with `status: success`.
- **Source:** `02-upload.py:1043`, `02-upload.py:1067`, `02-upload.py:1070`, `02-upload.py:1074`, `02-upload.py:1076`, `02-upload.py:1088`
- **Confidence:** [verified]
- **Related:** DEC-02

### REQ-11 - Download State
**WHEN** downloading available reports, **THE** download helper **SHALL** skip service account `90000003`, try credential-scoped receive directories, copy non-directory remote files to `downloads/<date>/<district>/`, and write per-account state as `success`, `empty`, or `failed`.
- **Acceptance:** `state/downloads/<date>/download/<user>.json` records downloaded filenames for successful accounts.
- **Acceptance:** Accounts with terminal download states are skipped unless `force = TRUE`.
- **Acceptance:** Failed connection or transfer state records the error class/status without raw credential strings, interpolated connection strings, passwords, or vendor-sensitive path details.
- **Source:** `02-upload.py:1106`, `02-upload.py:1111`, `02-upload.py:1115`, `02-upload.py:1157`, `02-upload.py:1175`, `02-upload.py:1183`, `02-upload.py:1190`
- **Confidence:** [inferred]
- **Related:** DEC-02, DEC-20, DEC-21

### REQ-11A - Sanitized Transfer Errors
**IF** an upload, download, archive inventory, or archive download operation fails, **THEN** the transfer helper **SHALL** print and persist only sanitized error class/status information.
- **Acceptance:** State JSON and console output do not include passwords, raw connection strings, or full exception messages that may contain sensitive connection details.
- **Acceptance:** Authentication failures are recorded as authentication failures, not raw exception payloads.
- **Source:** `02-upload.py:517`, `02-upload.py:583`, `02-upload.py:1046`, `02-upload.py:1140`, user interview on 2026-06-12
- **Confidence:** [inferred]
- **Related:** DEC-20

### REQ-11B - Authentication Failure Stops The Run
**IF** an SFTP upload or download login raises an authentication failure, **THEN** the transfer helper **SHALL** record a sanitized failed state for the current account and stop the multi-account run before attempting another credential.
- **Acceptance:** The credential immediately following a failed login is not attempted in the same run.
- **Acceptance:** The raised error identifies the affected district/account context without including the password or raw vendor exception.
- **Source:** `02-upload.py:987`, `02-upload.py:1106`, user refinement on 2026-08-25
- **Confidence:** [verified]
- **Related:** DEC-02, DEC-20, DEC-32

### REQ-12 - Processed Report Separation And Renaming
**WHEN** expanding and renaming downloaded reports, **THE** report processor **SHALL** keep DETAIL CSVs under `processed/<date>/<district>/detail`, keep other returned report files under `processed/<date>/<district>/reports`, and rename outputs with district, report type, and available `EFFDT`/`RUNDT` tags.
- **Acceptance:** DETAIL files are not included in `<district>_renamed.zip`.
- **Acceptance:** When a student-group suffix is configured, the reports-only ZIP name includes it as `<district><suffix>_renamed.zip` so parallel program bundles cannot collide or lose their group identity.
- **Acceptance:** Already-renamed `NSC_` files skip the rename step. Other optional operations, including watermarking, require separate rerun review.
- **Acceptance:** A report or DETAIL whose parsed SA differs from the selected processing account is rejected.
- **Acceptance:** Collision handling deduplicates only byte-identical content (size plus SHA-256); different content receives a `__dupN` filename even when byte counts match.
- **Source:** `02-upload.py:_renamed_zip_name`, `02-upload.py:expand_and_rename`, countywide CCR ZIP naming refinement on 2026-08-28
- **Confidence:** [verified]
- **Related:** DEC-03, DEC-08

### REQ-13 - Report Type Scaffold
**WHEN** scaffolding returned report types, **THE** scaffold helper **SHALL** compare DETAIL student fingerprints against known sent-batch manifests and auto-label a batch only when configurable conservative thresholds pass.
- **Acceptance:** The scaffold writes `downloads/<date>/report_type_scaffold.csv`.
- **Acceptance:** Rows whose evidence does not meet the configured auto-label thresholds remain `UNKNOWN`.
- **Acceptance:** Threshold values are treated as implementation defaults, not business rules.
- **Acceptance:** The scaffold includes overlap, precision, recall, F1, confidence, selection reason, related files, and top candidates.
- **Source:** `README.md:83`, `README.md:96`, `README.md:100`, `README.md:104`, `02-upload.py:388`, `02-upload.py:610`, `02-upload.py:669`, `02-upload.py:714`, `02-upload.py:773`, `02-upload.py:802`
- **Confidence:** [inferred]
- **Related:** DEC-12, DEC-22

### REQ-14 - Migrant Districtwide BASIC Extraction
**WHEN** extracting migrant districtwide BASIC reports from sorted downloads, **THE** migrant extractor **SHALL** copy only ZIP members whose report type is BASIC and whose internal ACT token equals the service-account token into `migrant_workflow/data/excel` or `migrant_workflow/data/pdf`.
- **Acceptance:** Extracted files are named `NSC_<District>__Districtwide_Basic.<ext>`.
- **Acceptance:** `migrant_workflow/migrant_districtwide_basic_manifest.csv` records district, source ZIP, member name, job, EFFDT, RUNDT, and output path.
- **Source:** `README.md:192`, `README.md:204`, `README.md:209`, `02-upload.py:911`, `02-upload.py:934`, `02-upload.py:943`, `02-upload.py:945`, `02-upload.py:952`, `02-upload.py:970`
- **Confidence:** [verified]
- **Related:** DEC-07

### REQ-15 - Migrant BASIC Parsing And Workbook
**WHEN** parsing migrant districtwide BASIC workbooks, **THE** parser **SHALL** normalize recognized NSC summary, progress, persistence, and MCI sections into district and county CSV outputs under `migrant_workflow/parsed`.
- **Acceptance:** Counts greater than class size are blanked in summary metrics.
- **Acceptance:** Persistence rates where second-year count exceeds first-year count are blanked.
- **Acceptance:** The workbook builder writes `migrant_workflow/output/_All<year>.xlsx` from parsed CSVs with a title matching the actual workbook scope.
- **Source:** `12-parse_migrant_basic_reports.R:13`, `12-parse_migrant_basic_reports.R:160`, `12-parse_migrant_basic_reports.R:450`, `12-parse_migrant_basic_reports.R:484`, `12-parse_migrant_basic_reports.R:661`, `13-build_migrant_workbook.py:327`, `13-build_migrant_workbook.py:366`
- **Confidence:** [inferred]
- **Related:** DEC-23

- **Sharing-copy implementation:** Workbook titles derive from the participating district labels or an explicit `--title`; multi-district output is labeled “Participating Districts.”

### REQ-16 - Full Detail Enrichment
**WHEN** building Class detail outputs, **THE** detail builder **SHALL** combine processed NSC DETAIL rows with RCCD-only enrollment rows, enrich the combined detail with graduate demographics and program fields, and write full-detail county, district, school, CSU, UCR, and RCCD outputs under `full_detail/`.
- **Acceptance:** NSC `Your_Unique_Identifier` values are normalized to SSID by removing leading, trailing, or embedded underscores.
- **Acceptance:** Vendor duplicate-removal exceptions are loaded from local `data/nsc_duplicate_corrections.csv` (`SSID`, `Last_Name`) rather than hard-coded as student/name pairs in the script. The share copy provides headers only, which excludes no rows (REQ-31).
- **Acceptance:** RCCD records already represented in NSC for the same `(SSID, Enrollment_Begin, College_Code/Branch)` are excluded from the RCCD-only add-in.
- **Acceptance:** CSU, UCR, and RCCD college-code lists used for specialized output files have an annual review recorded for the output year.
- **Acceptance:** Outputs include `full_detail/class_of_<COHORT_YEAR>_nsc_detail.parquet` and `.csv`.
- **Source:** `11-Detail.R:84`, `11-Detail.R:103`, `11-Detail.R:166`, `11-Detail.R:205`, `11-Detail.R:228`, `11-Detail.R:279`, `11-Detail.R:421`, `11-Detail.R:463`, `11-Detail.R:483`, `11-Detail.R:547`
- **Confidence:** [inferred]
- **Related:** DEC-04, DEC-19, DEC-25, DEC-26

### REQ-17 - Demographic Drift Guard
**IF** a non-empty outbound cohort produces missing, renamed, or all-blank demographic fields from an underlying source-format change, **THEN** the generator **SHALL** reject the run before upload with a schema-drift audit naming the affected fields and source file.
- **Acceptance:** A generated request or submission file is not considered upload-ready when all rows are blank for expected demographic fields such as gender, ethnicity, economically disadvantaged, English learner, disability, or program codes.
- **Acceptance:** The audit identifies whether the failure came from missing source columns, renamed source columns, parse failure, or an all-blank derived field.
- **Acceptance:** District-facing NSC demographic reports are not expected to be validated by district complaints or College-Career Readiness expertise after delivery.
- **Source:** `01-process.R:175`, `01-process.R:176`, `01-process.R:187`, `01-process.R:196`, `01-process.R:203`, `01-process.R:208`, `01p-process_selpa_request.R:186`, `01p-process_selpa_request.R:187`, `01p-process_selpa_request.R:198`, `01p-process_selpa_request.R:207`, `01p-process_selpa_request.R:214`, user interview on 2026-06-12
- **Confidence:** [inferred]
- **Related:** DEC-10

### REQ-18 - Charter CHRT Coverage
**WHEN** generating countywide annual submission files, **THE** countywide submission generator **SHALL** verify that each permitted charter LEA expected for the submission year is represented by an official 15.2 input before writing upload files.
- **Acceptance:** The run produces an audit listing expected permitted charter LEAs, observed CHRT/parquet coverage, and missing inputs.
- **Acceptance:** Missing expected charter 15.2 input is treated as missing data, not as evidence that the charter has zero in-scope students.
- **Source:** `01-process.R:6`, `01-process.R:7`, `01-process.R:12`, `01-process.R:30`, `01-process.R:40`, `01-process.R:58`, user interview on 2026-06-12
- **Confidence:** [inferred]
- **Related:** DEC-14

- **Sharing-copy implementation status:** Full CHRT ingestion/coverage verification is pending a reviewed field crosswalk and expected permitted-charter registry. Detected CHRT files stop the annual generator before output writes; they are no longer silently discarded.

### REQ-19 - SINF Charter District Mapping
**WHEN** enriching cohort rows with SINF names, **THE** SINF join step **SHALL** map charter records to the SINF district-code value used by the SINF extract before joining by SSID.
- **Acceptance:** For charter cases where the SINF extract stores the charter school code as `DistrictCode`, the cohort `SchoolCode` is used as the SINF join code.
- **Acceptance:** For non-charter cases, the cohort `DistrictCode` is used as the SINF join code.
- **Source:** `01-process.R:121`, `01-process.R:125`, `01-process.R:127`, user interview on 2026-06-12
- **Confidence:** [verified]
- **Related:** DEC-15

### REQ-20 - Charter CDS Normalization
**WHEN** joining charter cohort rows to account reference data, **THE** account-enrichment step **SHALL** normalize known charter CDS variants to the account-reference CDS before joining.
- **Acceptance:** A charter source CDS encoded as duplicated school code `(7 digit school code)(7 digit school code)` maps to the same account-reference row as the variant encoded with authorizer district code followed by school code.
- **Acceptance:** Known normalization mappings are auditable and do not require changing student row data by hand.
- **Source:** `01-process.R:129`, `01m-process_foster_request.R:104`, `01n-process_migrant_request.R:108`, user interview on 2026-06-12
- **Confidence:** [verified]
- **Related:** DEC-16

### REQ-21 - RCOE-Bundled Independent Charter Suppression
**WHILE** independent charter LEAs are bundled under RCOE's NSC account, **THE** countywide submission generator **SHALL** suppress those charter rows from RCOE district submission outputs.
- **Acceptance:** ACT codes `054763`, `054113`, and `050558` do not appear in RCOE district submission body rows while they are bundled under the RCOE NSC account.
- **Acceptance:** `data/account_refs.xlsx` contains no RCOE-bundled independent charter account-reference rows other than CBK / Come Back Kids while this workaround remains active.
- **Acceptance:** Any additional school-level suppression for the same issue is documented with the ACT/CDS, school name, NSC account-remediation status, and remediation owner.
- **Source:** `01-process.R:152`, `01-process.R:156`, `01-process.R:158`, user interview on 2026-06-12
- **Confidence:** [verified]
- **Related:** DEC-17

### REQ-22 - Raw SSID In Outbound Student Identifier
**WHEN** writing outbound StudentTracker submission or request rows, **THE** generator **SHALL** write SSID/student identifier fields without locally-added leading or trailing underscores.
- **Acceptance:** Annual submission rows do not prefix SSID with `_` in the student identifier field.
- **Acceptance:** Custom request rows do not prefix SSID with `_` in the student identifier field. Historical AVID, Alvord, TVUSD, and MVUSD generators follow the same raw-SSID contract; character SSIDs retain leading zeroes.
- **Acceptance:** Return-file validation still normalizes NSC-returned identifiers by stripping underscores before comparing to submitted SSIDs.
- **Source:** `01-process.R:169`, `01g-processAlvord.R:186`, `01u-processMVUSD.R:132`, `01v-process_tvusd_request.py:226`, `11-Detail.R:105`, user interview on 2026-06-12
- **Confidence:** [inferred]
- **Related:** DEC-19

### REQ-23 - Optional Report Watermarking
**WHERE** PDF report watermarking is requested, **THE** report processor **SHALL** apply the configured header text once to each target PDF under the processed reports directory.
- **Acceptance:** Watermark text is supplied by the processing call or operator input rather than hard-coded to one program, district, or date.
- **Acceptance:** A single processing run does not apply the same watermark twice to the same PDF.
- **Acceptance:** The complete watermark remains visible above vendor content and within the rendered page bounds for portrait, landscape, and rotated PDFs.
- **Source:** `02-upload.py:add_header_to_pdf`, `02-upload.py:expand_and_rename`, `03-watermark.py:56`, user interview on 2026-06-12, rendered CCR report QA on 2026-08-28
- **Confidence:** [inferred]
- **Related:** DEC-24

### REQ-24 - Standard Annual Request Cohorts
**WHEN** generating standard annual request files, **THE** request generator **SHALL** produce the configured countywide/program request cohorts for the project year before handling district- or project-specific ad-hoc requests.
- **Acceptance:** Standard annual request cohorts include countywide AVID, Foster, Migrant, and any other configured recurring countywide/program cohorts for the project year.
- **Acceptance:** Standard annual request cohorts use project-year parameters for cohort years, graduation windows, and source files rather than retained values from the copied prior-year folder.
- **Acceptance:** District/project-request cohorts remain separately named or suffixed so their outputs are distinguishable from standard annual request outputs.
- **Acceptance:** Countywide AVID builds each class from the same-year intersection of CALPADS 3.11 State Course `9211` participation and 15.2 regular graduates, then combines Classes 2022 through 2025 into the default historical request batch.
- **Acceptance:** A newly available class, including Class 2026, is opt-in until it belongs in the intended StudentTracker results cycle; it is never substituted silently for a completed historical class.
- **Acceptance:** The AVID generator rejects schema drift, writes required-field blockers locally, uses raw 10-digit SSIDs, and produces deterministic request/test files plus exact size-and-SHA-256 audit and production-only upload manifests before upload.
- **Acceptance:** Missing optional middle-name and suffix values are serialized as empty tab fields; source or in-memory missing values must never become outbound placeholder strings such as `NA`, `N/A`, `Null`, or `None`.
- **Acceptance:** Countywide AVID refreshes SA, ACT, district, and high-school mappings by CDS from the current `data/account_refs.xlsx` on every run and blocks unmatched CDS values rather than trusting cached account fields in the cohort RDS.
- **Source:** `01x-process_avid_request.py`, `tests/test_avid_request.py`, `01x-process_avid_request.R`, `tests/test_avid_request_contract.R`, `01m-process_foster_request.R:37`, `01n-process_migrant_request.R:49`, `01s-process_seal_biliteracy.R:37`, user refinements on 2026-08-24 and 2026-09-03
- **Confidence:** [verified]
- **Related:** REQ-03, REQ-05, REQ-06, REQ-17, REQ-22, DEC-28, DEC-29, DEC-33

### REQ-25 - Annual Project Rollover Hygiene
**WHEN** copying a prior StudentTracker project folder forward for a new fall project year, **THE** maintainer **SHALL** separate retained source/reference inputs from prior-year generated outputs and obsolete one-off scripts before generating new upload files.
- **Acceptance:** The copied project has documented project-year parameters for cohort year, graduation window, source file names, and standard request cohorts before outbound files are written.
- **Acceptance:** Prior-year `downloads/`, `processed/`, `requestfiles/`, `submissionfiles/`, `full_detail/`, root summary files, and runtime state are either removed, archived, or explicitly marked as retained history.
- **Acceptance:** Prior-year one-off district/project scripts are archived or documented before being left in the active project root.
- **Source:** user refinement on 2026-06-12, `docs/cruft_audit.md`
- **Confidence:** [inferred]
- **Related:** DEC-28, DEC-29, DEC-30

### REQ-26 - Summer CCR Multi-Class Request Cohorts
**WHEN** generating the summer College and Career Readiness request cycle, **THE** CCR request generator **SHALL** build separate AP, dual-enrollment (`CC`), IB, and State Seal of Biliteracy (`SSB`) request families from the configured four class-year source lists and route each request-ready student to the CDS-matched StudentTracker service account.
- **Acceptance:** The configured source set contains one AP, CC, IB, and SSB CSV for each of classes 2021-22 through 2024-25.
- **Acceptance:** Duplicate SSIDs within the same program family are audited and collapsed deterministically to one outbound row, while a student listed in different program families remains eligible for each separately named family.
- **Acceptance:** Output filenames end in `_CCR_AP`, `_CCR_CC`, `_CCR_IB`, or `_CCR_SSB`, and each file has a matching deterministic test file of at most 800 student rows.
- **Acceptance:** CC request rows set the StudentTracker dual-enrollment indicator to `Y`; other CCR families leave it blank.
- **Acceptance:** Source, duplicate, blocker, outbound, service-account, and file totals reconcile in a project-local audit summary and manifest before upload.
- **Source:** `01w-process_ccr_summer_request.py`, `tests/test_ccr_summer_request.py`
- **Confidence:** [verified]
- **Related:** REQ-03, REQ-05, REQ-06, REQ-09, REQ-10, REQ-17, REQ-22, REQ-24, DEC-27, DEC-29, DEC-31

### REQ-27 - Countywide Multi-Class CTE Completer Requests
**WHEN** generating the countywide CTE request cohort, **THE** CTE request generator **SHALL** combine the configured consecutive annual CALPADS 15.2 Account extracts that CALPADS filtered to `CTE Completer = Y`, retain the reporting/cohort year for every student, and route request-ready regular graduates through current account references.
- **Acceptance:** The default production scope is Classes 2023, 2024, and 2025, sourced respectively from `2022-2023_152_account_cte.parquet`, `2023-2024_152_account_cte.parquet`, and `2024-2025_152_account_cte.parquet` under the countywide annual snapshot prefix.
- **Acceptance:** CTE configuration with fewer than three cohort years is rejected before MinIO reads or local writes.
- **Acceptance:** A different consecutive cohort range, including Class 2026, requires an explicit `--cohort-years` selection; the generator does not silently add a newly available class to an established results cycle.
- **Acceptance:** Only rows identified by the CALPADS CTE-completer filter and classified as regular graduates (`StudentCompletionStatus == 100` and `CohortCategory == HSDiplomaGraduate`) enter candidate processing.
- **Acceptance:** Duplicate rows within a class are audited and collapsed deterministically; an SSID appearing in multiple cohort years stops the run rather than being assigned silently.
- **Acceptance:** Per-class source, regular-graduate, blocker, and outbound totals reconcile before any files are written, and `--preflight-only` reports aggregate totals without writing student-level artifacts.
- **Acceptance:** Output filenames end in `_CTE.txt` and use the request-file `H3`/`D3`/`T3` contract with raw 10-digit SSIDs, deterministic test files, required-field blockers, source-object checksums, and an exact production upload manifest.
- **Source:** `01y-process_cte_request.py`, `tests/test_cte_request.py`, CALPADS `calpads_152_cohort_outcomes_annual_cte` source workflow, user refinement on 2026-09-03
- **Confidence:** [verified]
- **Related:** REQ-03, REQ-05, REQ-06, REQ-17, REQ-22, REQ-24, DEC-28, DEC-29, DEC-37

### REQ-28 - CTE Return Processing
**WHEN** processing returned CTE files, **THE** report workflow **SHALL** stage only the DETAIL file whose student fingerprints exactly match the sent CTE roster and the ZIP bundle with the same NSC job, then rename, watermark, and package that account's reports as CTE outputs.
- **Acceptance:** CTE DETAIL rows remain isolated under the processed `detail` directory and are excluded from the reports-only ZIP.
- **Acceptance:** Renamed CTE report filenames include `_CTE`, and the reports-only bundle is named `<district>_CTE_renamed.zip`.
- **Acceptance:** Each CTE PDF contains the configured `CTE STUDENTTRACKER REPORT` header exactly once, while non-PDF report files remain unmodified.
- **Acceptance:** CTE return processing preserves the raw download tree and verifies the exact DETAIL/ZIP manifest before processing.
- **Source:** `02-upload.py:DEFAULT_REPORT_BATCH_SPECS`, `02-upload.py:CTE_REPORT_SUFFIX`, `02-upload.py:CTE_REPORT_HEADER`, `02-upload.py:expand_and_rename`, `README.md`
- **Confidence:** [verified]
- **Related:** REQ-12, REQ-13, REQ-23, REQ-27, DEC-03, DEC-08, DEC-24, DEC-38

### REQ-29 - Outbound Class-Span Invariant
**WHEN** preparing a StudentTracker outbound batch, **THE** workflow **SHALL** record the intended classes for `H3`/`D3` request batches and require exactly one class for `PH3`/`PD3` annual graduate submission batches.
- **Acceptance:** Request batches may contain one or more classes. The configured historical CTE batch retains its separate three-class scope under REQ-27.
- **Acceptance:** Request manifests record the declared class span and each service-account file's observed class span without imposing a multi-class file-type requirement.
- **Acceptance:** Every annual graduate submission derives exactly one graduation class from its graduation-date window before writing any `PH3`/`PD3` files.
- **Acceptance:** Countywide AVID uses the maintained Python generator; its historical multi-class default does not prohibit explicitly configured single-class requests.
- **Source:** `studenttracker_scope.py`, `01-process.R`, `01w-process_ccr_summer_request.py`, `01x-process_avid_request.py`, `01x-process_avid_request.R`, `01y-process_cte_request.py`, `02-upload.py`, user refinement on 2026-09-03
- **Confidence:** [verified]
- **Related:** REQ-04, REQ-05, REQ-24, REQ-26, REQ-27, DEC-11, DEC-33, DEC-37, DEC-39

### REQ-30 - Rancho Mirage SMART Request
**WHEN** generating the SMART special request, **THE** generator **SHALL** match the supplied workbook district student IDs to Class 2025 Rancho Mirage High records in Palm Springs Unified, exclude the user-identified non-graduate, and write one validated request plus test and audit files.
- **Acceptance:** Workbook IDs join by `(DistrictCode, LocalID)` rather than being treated as SSIDs; outbound IDs are matched raw SSIDs.
- **Acceptance:** User exclusions and required-field blockers reconcile with source and outbound totals; no absent attendance date is invented.
- **Source:** `01z-process_smart_request.py`, user instructions on 2026-10-28
- **Related:** REQ-03, REQ-05, REQ-06, REQ-07, REQ-29, DEC-40

### REQ-31 - Share Copy Contains No Operational Records
**WHEN** preparing a share copy, **THE** package **SHALL** include reviewed source and documentation, empty operational folders, header-only reference templates, and explicitly synthetic examples.
- **Acceptance:** Exclude live credentials, student data, reports, audit/state history, Git history, caches, saved R sessions, and original workbook metadata.
- **Acceptance:** `11-Detail.R` loads optional correction rows from the required local `data/nsc_duplicate_corrections.csv` template; the supplied template has only `SSID,Last_Name` headers and produces no exclusions. No real student/name pairs are embedded in code.
- **Acceptance:** Package contents and checks are recorded in `SHARING_NOTES.md` and `SHARE_MANIFEST.csv`.
- **Related:** REQ-16, DEC-25, DEC-41

### REQ-32 - Account Source Structure And Report Naming
**WHEN** maintaining account mappings or preparing renamed reports, **THE** workflow **SHALL** distinguish school/CDS mappings from transfer credentials, preserve reference codes as text, and document how SA/ACT scope determines report names.
- **Acceptance:** The share workbook reproduces header-only `Refs`, `NCES`, and `CDS` sheets; `Refs` is first and contains the original ten columns.
- **Acceptance:** `creds.csv` is separately documented as `sa,user,pass,district`; a login is not inferred from an SA or school code.
- **Acceptance:** School report lookup uses `(SA, normalized ACT)` and rejects conflicting school names. Districtwide reports use an ACT token equal to SA.
- **Acceptance:** Documentation explains report type, program suffix, vendor EFFDT/RUNDT tags, local folder date, DETAIL separation, and content-based collision handling.
- **Acceptance:** Account-reference provenance reflects maintainer-confirmed multiple NSC source files and possible local adjustments. Exact source versions, assembly steps, and adjustments remain pending rather than assumed; future updates retain source/date references and record applied adjustments with reasons.
- **Related:** REQ-03, REQ-12, REQ-13, DEC-42

### REQ-33 - Public Repository Boundary
**WHEN** publishing the reference implementation, **THE** repository **SHALL** contain only reviewed source, documentation, synthetic fixtures, and header-only templates, with a new history that excludes operational project history.
- **Acceptance:** Operational SA values, historical login names, and internal bucket identifiers are replaced by documented examples.
- **Acceptance:** Credentials and account-reference templates are tracked under `templates/`; their live paths remain ignored and untracked.
- **Acceptance:** Local template initialization never overwrites existing inputs.
- **Acceptance:** The exact staged file set and new commit history pass the release review before upload.
- **Related:** REQ-31, REQ-32, DEC-45

## Retired

| ID | Retired | Reason |
|----|---------|--------|

## Traceability

Reconciled 2026-11-10 for the sharing copy. Source line references elsewhere retain historical extraction locations; use symbol names and current files when navigating. “Tested” below refers to synthetic or mocked evidence, not a production-data validation.

| REQ | Implemented in | Verified by | Status and limits |
|---|---|---|---|
| REQ-01 | `01-process.R`, `annual_submission_config.R` | `tests/test_annual_submission_config.R` | configured annual source/window and three exclusions verified with synthetic rows; complete source coverage remains manual |
| REQ-02 | annual/program R SINF steps | no dedicated SINF regression test | implemented latest-by merge; not verified against private SINF inputs |
| REQ-03 | request helpers, annual CDS join, report lookup | CCR/CTE tests; `tests/test_accounts_and_report_processing.py` | partial coverage: conflicting SA/ACT names rejected; not every legacy join is tested |
| REQ-04 | `01-process.R` | SSID serialization and annual config tests | partial; no complete annual PH3/PD3/PT3 fixture test |
| REQ-05 | custom request generators | Python CCR/CTE tests; R AVID contract test | maintained contracts tested; historical variants not uniformly covered |
| REQ-06 | request generator blocker logic | CCR/CTE tests and manual audits | legacy blocker behavior still needs broader regression coverage |
| REQ-07 | TVUSD/MVUSD/SMART generators | prior manual source reconciliation | no comprehensive synthetic district-scope regression suite |
| REQ-08 | `01g-processAlvord.R` | raw SSID test; runbook | multi-year Alvord membership not regression-tested |
| REQ-09 | `02-upload.py` | class-span/authentication tests | class declarations tested; complete exact-file/state/dry-run coverage remains partial |
| REQ-10 | `02-upload.py` | remote-size verification in code | no dedicated success/size-mismatch integration test |
| REQ-11 | `02-upload.py` | authentication and account/report tests | receive fallbacks credential-scoped; transfer errors persisted by class |
| REQ-11A | `02-upload.py` | synthetic archive/download/upload error tests | class-only persisted errors; real vendor transfers not exercised |
| REQ-11B | `02-upload.py` | `tests/test_transfer_auth_fail_fast.py` | primary upload/download login failures stop the multi-account run |
| REQ-12 | `02-upload.py` | account/report integration tests; ZIP naming tests | report/DETAIL isolation, foreign SA, names, date tags, and collisions tested |
| REQ-13 | `02-upload.py` report scaffold | manual scaffold review | heuristic classification; not a proof of program scope |
| REQ-14 | migrant BASIC extraction helper | manual manifests | no dedicated extraction regression test |
| REQ-15 | migrant parser/workbook builder | synthetic title test; prior parse review | title scope corrected; full parsed metric/workbook QA not rerun |
| REQ-16 | `11-Detail.R`, `rccd/*.R` | `tests/test_detail_corrections.R` | correction input externalized; private RCCD/NSC enrichment untested; annual college review remains manual |
| REQ-17 | CCR/CTE checks and AVID source checks | CCR/CTE tests | partially implemented; demographic protections not uniform across legacy R scripts |
| REQ-18 | annual CHRT guard | `tests/test_annual_submission_config.R` | partial: CHRT presence rejected; crosswalk and permitted-charter coverage registry missing |
| REQ-19 | R charter SINF join logic | documented interview decision | intent confirmed; no dedicated join fixture |
| REQ-20 | R charter CDS rewrites | documented interview decision | hard-coded variant mapping; no dedicated normalization fixture |
| REQ-21 | account reference/charter suppressions | manual account review | not automatically enforced or tested for every reference row |
| REQ-22 | annual/custom request generators | `tests/test_outbound_ssid_contract.R`; existing request tests | raw character SSIDs in share copy; return normalization retained |
| REQ-23 | `02-upload.py` | `tests/test_pdf_watermark.py` | maintained rendered watermark verified; standalone main retired; general repeated watermarking not guaranteed idempotent |
| REQ-24 | maintained AVID and recurring program scripts | AVID Python/R tests | AVID source pairing and request contract tested; legacy programs have narrower coverage |
| REQ-25 | annual config; sharing docs | annual config test; package review | partial: clean share package and annual settings; other historical source dates remain explicit |
| REQ-26 | `01w-process_ccr_summer_request.py` | `tests/test_ccr_summer_request.py` | program scope/deduplication and request contracts tested |
| REQ-27 | `01y-process_cte_request.py` | `tests/test_cte_request.py` | multi-class sources, graduate selection, and request fields tested |
| REQ-28 | CTE report workflow | ZIP/watermark/account/report tests; exact-manifest runbook | naming/isolation tested; operational roster/job pairing still required |
| REQ-29 | scope helpers and generators | scope and request/authentication tests | declared request classes; annual submissions require one class |
| REQ-30 | `01z-process_smart_request.py` | prior source-to-outbound manual reconciliation | no dedicated synthetic SMART end-to-end regression test |
| REQ-31 | sanitized templates, package, local correction CSV | package inventory/header checks; synthetic tests | share-copy-only sanitization; no live inputs included |
| REQ-32 | Refs/NCES/CDS templates; account/naming docs | workbook header readback; account/report integration tests | schema/runtime contracts documented; multiple NSC sources and possible adjustments confirmed as provenance; detailed lineage remains deferred |

| REQ-33 | public template initialization and release boundary | staged-content/privacy checks, new-history review, synthetic tests | public snapshot only; production inputs excluded |
