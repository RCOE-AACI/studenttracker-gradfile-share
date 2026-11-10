#!/usr/bin/env python3
# SMART request: workbook identifiers are LocalIDs, resolved within the configured district/class before SSID-based outbound serialization. REQ-30.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
"""Build the source-bounded Rancho Mirage SMART request (REQ-30, DEC-40)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import polars as pl
from openpyxl import load_workbook

from studenttracker_scope import validate_request_cohort_years

spec = importlib.util.spec_from_file_location('request_contract', Path(__file__).with_name('01w-process_ccr_summer_request.py'))
contract = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(contract)

DISTRICT_CODE = '3367173'
SCHOOL_CODE = '0127316'
SERVICE_ACCOUNT = '90000005'
COHORT_YEAR = 2025


def generate(args: argparse.Namespace) -> dict:
    validate_request_cohort_years((COHORT_YEAR,), context='SMART request')
    workbook = load_workbook(args.source, read_only=True, data_only=True)
    source_rows = []
    for row_number, row in enumerate(workbook.active.values, 1):
        local_id = contract.normalize_scalar(row[0])
        if re.fullmatch(r'\d{10}', local_id):
            source_rows.append({'SourceRow': row_number, 'LocalID': local_id})
    workbook.close()
    source = pl.DataFrame(source_rows)
    if source.is_empty() or source['LocalID'].n_unique() != source.height:
        raise ValueError('SMART source must contain nonempty, unique district student IDs')
    exclusions = set(args.exclude_local_id)
    if exclusions - set(source['LocalID'].to_list()):
        raise ValueError('An excluded LocalID is absent from the source workbook')
    excluded = source.filter(pl.col('LocalID').is_in(sorted(exclusions))).with_columns(
        pl.lit('User confirmed student did not graduate from Palm Springs').alias('ExclusionReason')
    )
    selected = source.filter(~pl.col('LocalID').is_in(sorted(exclusions)))
    columns = [
        'LocalID', 'SSID', 'DistrictCode', 'SchoolCode', 'CohortYear',
        'BirthDate', 'StudentEnrollmentExitDate', 'Gender', 'EthnicityRace',
        'MigrantEd', 'StudentswithDisabilities', 'SocioEconomicallyDisadvantaged',
        'EnglishLearner', 'FosterYouth', 'Homeless', 'Sealofbiliteracy', 'UC_CSURequirementsMet',
    ]
    cohort = pl.scan_parquet(args.cohort).select(columns).filter(
        (pl.col('DistrictCode') == DISTRICT_CODE) &
        (pl.col('CohortYear') == str(COHORT_YEAR)) &
        pl.col('LocalID').is_in(selected['LocalID'].implode())
    ).collect()
    if cohort['LocalID'].n_unique() != cohort.height:
        raise ValueError('Ambiguous LocalID mapping within district/class')
    candidate = selected.join(cohort, on='LocalID', how='left', validate='1:1')
    if candidate['SSID'].null_count():
        raise ValueError('A non-excluded source ID has no Class 2025 district match')
    if candidate.filter(pl.col('SchoolCode') != SCHOOL_CODE).height:
        raise ValueError('A source student maps outside Rancho Mirage High')
    if candidate['SSID'].n_unique() != candidate.height:
        raise ValueError('Multiple source IDs map to the same SSID')
    blank_fields = [column for column in contract.EXPECTED_DEMOGRAPHIC_COLUMNS
                    if candidate.filter(pl.col(column).fill_null('').str.strip_chars() != '').is_empty()]
    if blank_fields:
        raise ValueError(f'Demographic schema drift: all blank {blank_fields}')
    candidate = candidate.with_columns(
        pl.concat_str('DistrictCode', 'SchoolCode').alias('CDS'),
        contract.parse_source_date('BirthDate').alias('BirthDateParsed'),
        contract.parse_source_date('StudentEnrollmentExitDate').alias('ExitDateParsed'),
        pl.lit('SMART').alias('Program'),
    )
    # Name-bearing data stays in memory until the immediate outbound deliverable.
    ready, blockers = contract.enrich_and_classify(
        candidate, contract.read_account_refs(args.account_refs), contract.read_sinf(args.sinf)
    )
    if ready.is_empty():
        raise ValueError('No request-ready SMART records')
    if ready['SA'].unique().to_list() != [SERVICE_ACCOUNT]:
        raise ValueError('Unexpected SMART service account')
    assert source.height == excluded.height + blockers.height + ready.height
    run_date = args.run_date
    from datetime import datetime
    datetime.strptime(run_date, '%Y%m%d')
    district = ready['District'].unique().to_list()
    if len(district) != 1:
        raise ValueError('SMART must map to one district')
    filename = f'{run_date}_{SERVICE_ACCOUNT}_{contract.safe_filename_token(district[0])}_SMART.txt'
    output = Path('requestfiles') / filename
    test_output = Path('requestfiles/test_file') / filename
    audit_prefix = Path('audit') / f'{run_date}_smart_request'
    if output.exists() or test_output.exists():
        raise FileExistsError('Refusing to overwrite an existing SMART request')
    body = [contract.request_body_row(row) for row in ready.sort('SSID').iter_rows(named=True)]
    header = [['H3', SERVICE_ACCOUNT, '', district[0], run_date, 'SE', 'D']]
    contract.write_tsv_atomic(output, header + body + [['T3', str(len(body) + 2)]], False)
    validation = contract.validate_request_file(output, SERVICE_ACCOUNT, len(body), run_date)
    test_body = body[:800]
    contract.write_tsv_atomic(test_output, header + test_body + [['T3', str(len(test_body) + 2)]], False)
    contract.validate_request_file(test_output, SERVICE_ACCOUNT, len(test_body), run_date)
    contract.write_audit_csv(excluded, Path(f'{audit_prefix}_exclusions.csv'))
    contract.write_audit_csv(blockers.select('SourceRow', 'LocalID', 'SSID', 'BlockerReasons'), Path(f'{audit_prefix}_blockers.csv'))
    contract.write_audit_csv(ready.select('SourceRow', 'LocalID', 'SSID', 'CDS', 'SA', 'ACT', 'CohortYear'), Path(f'{audit_prefix}_roster.csv'))
    sources = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [args.source, args.cohort, args.account_refs, args.sinf]}
    summary = {
        'source_students': source.height, 'user_exclusions': excluded.height,
        'blocked_students': blockers.height, 'outbound_students': ready.height,
        'service_account': SERVICE_ACCOUNT, 'district': district[0],
        'cohort_years': [COHORT_YEAR], 'observed_cohort_years': [COHORT_YEAR],
        'file': validation, 'test_file': str(test_output), 'source_sha256': sources,
        'uploaded': False, 'excluded_local_ids': sorted(exclusions),
    }
    Path(f'{audit_prefix}_manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('data/SMART Program for Rancho Mirage HS class of 2025.xlsx'))
    parser.add_argument('--cohort', type=Path, default=Path('data/2024-2025_152_account.parquet'))
    parser.add_argument('--account-refs', type=Path, default=Path('data/account_refs.xlsx'))
    parser.add_argument('--sinf', type=Path, default=Path('data/sinf_merge.parquet'))
    parser.add_argument('--run-date', required=True)
    parser.add_argument('--exclude-local-id', action='append', default=[])
    print(json.dumps(generate(parser.parse_args()), indent=2))
