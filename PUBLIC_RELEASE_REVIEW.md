# Public release review — 2026-11-10

This repository is a sanitized reference snapshot. The production project, its Git history, and its data directories were not imported into this repository.

## Included content

- Reviewed Python/R source, specifications, workflow documentation, and tests using invented fixtures.
- Header-only input templates under `templates/`: credential CSV schema, local duplicate-correction CSV schema, and a workbook with the original `Refs`, `NCES`, and `CDS` headers and no records.
- Public school/district identifiers and names needed to explain the workflow, plus historical project/class dates.
- Synthetic account-routing values, an example login in historical documentation, and an example bucket name. Replace these examples in a private operational checkout before use.

## Excluded or replaced

- Student source extracts, identifiers from real records, names from real records, dates of birth from real records, submission files, returned reports, small-cohort reconciliation counts, and student-specific correction pairs.
- Working passwords, access tokens, credential backups, cloud/SQL credential files, local account rows, transfer state, private hostnames, and the original internal bucket name.
- Operational SA routing constants and a historical real SFTP username, replaced consistently by examples. An SA is not a password, but the real values are unnecessary for this release.
- Original Git history, R session/history files, editor state, virtual environments, Python caches, and machine-specific files.

## Local data boundary

Only templates are tracked. Run `python3 prepare_local_templates.py` after cloning to create ignored local input files. The initializer never overwrites an existing file. This avoids tracking a live credential path whose later edits could contain real credentials.

The manifest lists the exact reviewed public files. Locally initialized `creds.csv`, `data/account_refs.xlsx`, and `data/nsc_duplicate_corrections.csv` are excluded from the manifest, commit, and public archive. Do not force-add private inputs or generated outputs.

## Checks performed

- Verified the exact tracked file inventory and rejected symlinks, unexpected data/binary formats, and unreviewed files.
- Read back the template workbook: three visible sheets with the exact original header schemas and zero data rows. Confirmed both CSV input templates contain headers only.
- Compared the original embedded student correction identifiers/surnames against all release payloads, including workbook XML, without displaying those values. None remain.
- Checked for private keys, credential-token formats, personal machine paths, email addresses, private hostnames, original bucket/login identifiers, and original operational SA values. No such values remain in the reviewed payload.
- Remaining student-format identifier literals are confined to explicitly synthetic fixtures/examples. Placeholder passwords in mocked tests are invented and do not authenticate to a service.
- All 39 Python tests and all four R test scripts passed. Python/R source passed syntax checks. No real SFTP transfer, warehouse query, or object-storage connection was used for validation.
- Initialized a new repository from this snapshot only. The release commit uses a GitHub noreply address; no operational history is included.

## Readiness and limits

The reviewed snapshot is suitable for public code/reference sharing based on these content checks. It is not an operational dataset or a claim that every legacy pipeline is production-ready. Charter coverage, legacy validation, annual configuration, and report-selection limitations are documented in `docs/workflow_status.md`.

The review applies to this snapshot. Newly supplied real inputs and future edits require their own review before publication.
