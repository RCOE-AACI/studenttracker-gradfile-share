# Account references and report naming

This document describes the local file contracts and the behavior of `02-upload.py`. All examples below are synthetic. The shared workbook and credential file contain headers only.

## The account sources serve different purposes

| Source | Purpose | Row level |
|---|---|---|
| District `AccountReferenceSheet*.xls` exports | Vendor account/school reference material. A sampled local sheet has `HIGH SCHOOL NAME`, `ACT CODE`, and `NCES CODE` headings. | Formatted district account sheet, with a school table below the account heading; not a ready-to-join CSV. |
| `data/AccountRefs/ncesdata_*.xls` | NCES school-reference material present in the original project. | Source-dependent school reference. |
| `data/AccountRefs/pubschls.xlsx` | CDE public-school reference material present in the original project. | School reference. |
| `data/account_refs.xlsx` | Maintained crosswalk used by the generators and report renamer. | Main `Refs` sheet: a school/CDS-to-SA/ACT mapping. |
| `creds.csv` | Private SFTP access and the local district folder label. | One transfer login/routing record; it is not the school crosswalk. |

The maintainer clarified on 2026-11-10 that `account_refs.xlsx` combines multiple NSC files and may include local adjustments. Treat it as a maintained composite crosswalk, not an untouched copy of one NSC export. No workbook rebuild script was identified in this project. The exact source-file versions, combination steps, and possible adjustments remain undocumented; whether assembly is manual or scripted is not established. NCES and CDE files are also present locally, but their role in building the workbook is not confirmed. Original vendor source forms are excluded from the sharing package because they may contain account/contact information.

For future updates, retain the source filenames/dates and record any applied adjustments and their reasons. Replacing the workbook with a fresh vendor export could lose a local mapping correction; reconcile changes before replacing the maintained crosswalk.

## Workbook structure

`Refs` is the first sheet and the active crosswalk. Its exact column order is:

`District, SA, HSName, ACT, NCES, CDS, Status, ClosedDate, Charter, Funding`

| Column | Meaning and use |
|---|---|
| `District` | District/LEA display name used by generation workflows. |
| `SA` | StudentTracker service-agreement/account identifier. It routes a request/submission to an account and appears in the outbound header and filename. Preserve as text, normally eight digits. |
| `HSName` | School display name used in applicable outbound fields and school-level returned-report names. |
| `ACT` | Vendor high-school code. Preserve as text, usually six characters; accepted alphanumeric codes must remain intact. It identifies a school within an SA when renaming returns. |
| `NCES` | School NCES identifier, retained for reference/crosswalk maintenance. It is not an SFTP login or an SA. |
| `CDS` | Fourteen-character California school key: seven-character district code plus seven-character school code. Generation workflows use it to attach SA/ACT/school information to a student. |
| `Status`, `ClosedDate`, `Charter`, `Funding` | School reference metadata. Their presence does not mean every generator automatically filters closed schools or enforces charter policy. |

One SA can appear on many school rows. Do not deduplicate the reference workbook to one row per SA: doing so loses school/CDS/ACT mappings. The intended mapping is one consistent account/school assignment per CDS; exact repeated rows can be collapsed, while conflicting assignments need review. Newer request helpers reject conflicting CDS mappings. Legacy R generators do not all enforce the same validation yet.

The renamer separately requires one consistent `HSName` per `(SA, ACT)` pair. It now rejects conflicting school names rather than silently choosing the last row. It normalizes numeric ACT codes to six characters and scopes the lookup to the SA, so an ACT in another account cannot supply the school name.

The supporting sheets reproduce the original schema:

- `NCES`: `NCES School ID, State School ID, CDS, School Name, District`
- `CDS`: `CDSCode, NCESDist, NCESSchool, StatusType, County, District, School, OpenDate, ClosedDate, Charter, FundingType`

Current generators read `Refs` or the first worksheet. The supporting sheets are reference material; merely adding them does not automatically refresh `Refs`.

## Credential CSV structure

`sa,user,pass,district`

- `sa` is the same account identifier represented by `Refs.SA` and vendor filenames.
- `user` is the SFTP username. It is distinct from the SA and need not resemble it.
- `pass` is the private SFTP password. It must never enter the shared package.
- `district` is the local folder/report label used by transfer and processing helpers. It may be shorter than `Refs.District`; keep it consistent across downloads and processing for the same account.

Generation obtains routing from the school crosswalk. Transfer helpers match outbound filenames by SA, then use the credential login. Returned files are found under `downloads/<local-date>/<creds.district>/`. The renamer uses `creds.district` for the report prefix and `(SA, ACT)` from `Refs` for the school label.

For example, two fictional schools can have different CDS and ACT values but share SA `10000001`. Both outbound sets belong to that SA's login; each returned school report is distinguished by its ACT. Never join students to this crosswalk by school display name when a CDS is available.

## Why reports are renamed

Vendor filenames emphasize account, school-code, job, and date tokens. Local names make the district, school or districtwide scope, report type, and requested student group readable to recipients. Renaming changes the filename, not the report's scope or its contents. A configured PDF header is a separate optional operation.

Recognized vendor report names begin:

`<user>_<SA>_<ACT-or-SA>_<job>_...`

The report name produced is:

`NSC_<district>_<school-or-_Districtwide><type><suffix>[_EFFDTyyyymmdd][_RUNDTyyyymmdd].<ext>`

Rules:

1. The parsed SA must match the processing credential's SA. A mismatch stops processing instead of labeling another account's report with this district's name.
2. An ACT token equal to the SA denotes a districtwide report. The resulting name intentionally contains `__Districtwide`: the template separator plus the scope label's leading underscore.
3. Otherwise, look up the school by `(SA, normalized ACT)`. Vendor prefixes `HS` and `HSA` are normalized. A missing school mapping retains the code as `_ACT<code>`; it does not guess a school.
4. Recognized report types are `_Academics`, `_Basic`, `_Demographics`, and `_Top25`. Other types receive `_Unknown`. Unrecognized filename layouts remain unchanged for review.
5. The caller supplies a program suffix such as `_CTE` or `_CCR_AP` only after verifying the batch. The renamer does not infer a program from a friendly filename.
6. `EFFDT` and `RUNDT` tags come from the vendor filename. RUNDT is shortened to its first eight digits for the output name. The `eff_date` function argument is the **local download-folder date**, not an instruction to replace the vendor's EFFDT.
7. Already named `NSC_` files skip the rename step. This does not promise that every optional operation, especially repeated watermarking, is idempotent.
8. Collisions are compared by size and SHA-256. Identical content is deduplicated; different content is retained with `__dup2`, `__dup3`, etc., even when byte counts match.

Synthetic examples:

| Kind | Local name |
|---|---|
| School BASIC, CTE | `NSC_Example_Example High_Basic_CTE_EFFDT20260101_RUNDT20260102.xls` |
| Districtwide BASIC, CTE | `NSC_Example__Districtwide_Basic_CTE_EFFDT20260101_RUNDT20260102.pdf` |
| DETAIL, CTE | `NSC_Example_Detail_10000001_987_CTE_EFFDT20260101_RUNDT20260102.csv` |
| Reports-only archive | `Example_CTE_renamed.zip` |

## DETAIL isolation and batch selection

Processed reports go under `processed/<local-date>/<district>/reports/`. Student-level DETAIL CSVs go under the separate `detail/` directory and retain SA and job in their friendly names. Reports-only ZIPs include the contents of `reports/` and exclude DETAIL. Raw files in `downloads/` remain the evidence copy.

By default, `expand_and_rename(..., comprehensive_only=True)` selects the latest matching RUNDT and then the largest DETAIL file on that date, pairing ZIPs by the parsed job. This is a heuristic for comprehensive results; it is **not proof of program membership**. When requests from several programs coexist, first isolate the exact roster-matched DETAIL and matching job ZIP, as described in the CTE return runbook. Use explicit `filter_rundt`, `filter_effdt`, suffix, and account scope. A suffix labels a verified selection; it cannot make an ambiguous selection correct.

See REQ-03, REQ-12, REQ-13, REQ-28, REQ-32, DEC-42, and the synthetic integration test `tests/test_accounts_and_report_processing.py`.
