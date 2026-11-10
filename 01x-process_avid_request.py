#!/usr/bin/env python3
# Maintained AVID generator: intersect same-year course and graduate snapshots, refresh account mapping, and validate request files. REQ-24.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
"""Build countywide multi-class AVID StudentTracker request files.

Each class is the same-year intersection of CALPADS 3.11 State Course 9211
participants and regular graduates in the annual CALPADS 15.2 Account extract.
The default request combines Classes 2022 through 2025. MinIO is read-only and
student-level values are never printed to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from datetime import date
from pathlib import Path

import boto3
import polars as pl

from studenttracker_scope import parse_year_expression, validate_request_cohort_years


DEFAULT_COHORT_YEARS = "2022-2025"
AVID_STATE_COURSE = "9211"
COURSE_REQUIRED_COLUMNS = ("SSID", "StateCourse", "DistrictCode", "School_Code")


def _load_request_contract_module():
    """Reuse the audited StudentTracker serialization/enrichment contract."""
    path = Path(__file__).with_name("01y-process_cte_request.py")
    spec = importlib.util.spec_from_file_location("studenttracker_request_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load request contract module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


request_contract = _load_request_contract_module()


def parse_cohort_years(value: str) -> tuple[int, ...]:
    return validate_request_cohort_years(
        parse_year_expression(value), context="AVID request batch"
    )


def annual_source_key(prefix: str, cohort_year: int, report: str) -> str:
    report_year = f"{cohort_year - 1}-{cohort_year}"
    suffix = {"course": "311_snap", "graduate": "152_account"}.get(report)
    if suffix is None:
        raise ValueError(f"Unknown AVID source report type: {report}")
    return f"{prefix.rstrip('/')}/year={cohort_year}/{report_year}_{suffix}.parquet"


def _get_parquet(
    client: object,
    *,
    bucket: str,
    key: str,
    columns: tuple[str, ...],
    source_label: str,
) -> tuple[pl.DataFrame, bytes, dict[str, object]]:
    response = client.get_object(Bucket=bucket, Key=key)
    payload = response["Body"].read()
    try:
        frame = pl.read_parquet(io.BytesIO(payload), columns=list(columns))
    except Exception as exc:
        raise ValueError(
            f"{source_label} schema/read failure for s3://{bucket}/{key}"
        ) from exc
    return frame, payload, response


def load_avid_cohorts(
    client: object,
    bucket: str,
    prefix: str,
    cohort_years: tuple[int, ...],
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    cohort_years = validate_request_cohort_years(
        cohort_years, context="AVID request batch"
    )
    matched_frames: list[pl.DataFrame] = []
    duplicate_frames: list[pl.DataFrame] = []
    source_rows: list[dict[str, object]] = []
    cohort_rows: list[dict[str, object]] = []

    for cohort_year in cohort_years:
        report_year = f"{cohort_year - 1}-{cohort_year}"
        course_key = annual_source_key(prefix, cohort_year, "course")
        graduate_key = annual_source_key(prefix, cohort_year, "graduate")
        course, course_payload, course_response = _get_parquet(
            client,
            bucket=bucket,
            key=course_key,
            columns=COURSE_REQUIRED_COLUMNS,
            source_label="3.11 AVID course",
        )
        graduate, graduate_payload, graduate_response = _get_parquet(
            client,
            bucket=bucket,
            key=graduate_key,
            columns=(*request_contract.CTE_COHORT_REQUIRED_COLUMNS, "CohortYear"),
            source_label="15.2 graduate",
        )

        course = course.with_columns(
            request_contract.normalize_expr("SSID").alias("SSID"),
            request_contract.normalize_expr("StateCourse").alias("StateCourse"),
            request_contract.normalize_expr("DistrictCode", 7).alias("DistrictCode"),
            request_contract.normalize_expr("School_Code", 7).alias("School_Code"),
        )
        avid_course = course.filter(
            pl.col("StateCourse").str.contains(
                rf"^{AVID_STATE_COURSE}(?:-|$)"
            )
            & (pl.col("SSID") != "")
        )
        invalid_avid_ids = avid_course.filter(
            ~pl.col("SSID").str.contains(r"^\d{10}$")
        )
        if not invalid_avid_ids.is_empty():
            raise ValueError(
                f"3.11 AVID identifier drift for s3://{bucket}/{course_key}: "
                f"{invalid_avid_ids.height} invalid SSID rows"
            )
        avid_ssids = avid_course.select("SSID").unique()

        graduate = graduate.with_columns(
            request_contract.normalize_expr("SSID").alias("SSID"),
            request_contract.normalize_expr("DistrictCode", 7).alias("DistrictCode"),
            request_contract.normalize_expr("SchoolCode", 7).alias("SchoolCode"),
            request_contract.normalize_expr("StudentCompletionStatus").alias(
                "StudentCompletionStatus"
            ),
            request_contract.normalize_expr("CohortCategory").alias("CohortCategory"),
            request_contract.normalize_expr("CohortYear").alias("ReportedCohortYear"),
            request_contract.parse_date_expr("BirthDate").alias("BirthDateParsed"),
            request_contract.parse_date_expr("StudentEnrollmentExitDate").alias(
                "ExitDateParsed"
            ),
        ).with_columns(
            pl.concat_str("DistrictCode", "SchoolCode").alias("CDS")
        ).with_columns(
            pl.when(pl.col("CDS") == "01252370125237")
            .then(pl.lit("33103300125237"))
            .otherwise(pl.col("CDS"))
            .alias("CDS")
        )
        invalid_graduate_ids = graduate.filter(
            ~pl.col("SSID").str.contains(r"^\d{10}$")
        )
        if not invalid_graduate_ids.is_empty():
            raise ValueError(
                f"15.2 identifier drift for s3://{bucket}/{graduate_key}: "
                f"{invalid_graduate_ids.height} invalid SSID rows"
            )
        regular = graduate.filter(
            (pl.col("StudentCompletionStatus") == "100")
            & (pl.col("CohortCategory") == "HSDiplomaGraduate")
            & (pl.col("ReportedCohortYear") == str(cohort_year))
        ).with_columns(
            pl.lit(cohort_year).alias("CohortYear"),
            pl.lit(report_year).alias("SourceReportYear"),
            pl.lit(date(cohort_year - 1, 9, 1)).alias("GraduationWindowStart"),
            pl.lit(date(cohort_year, 8, 31)).alias("GraduationWindowEnd"),
        )
        duplicates = regular.group_by("SSID").agg(
            pl.len().alias("GraduateRows"),
            pl.col("CDS").n_unique().alias("DistinctCDS"),
        ).filter(pl.col("GraduateRows") > 1).with_columns(
            pl.lit(cohort_year).alias("CohortYear"),
            pl.lit(report_year).alias("SourceReportYear"),
        ).select(
            "CohortYear", "SourceReportYear", "SSID", "GraduateRows", "DistinctCDS"
        ).sort("SSID")
        regular = regular.sort(
            ["SSID", "ExitDateParsed", "CDS"],
            descending=[False, True, False],
            nulls_last=True,
        ).unique(subset=["SSID"], keep="first", maintain_order=True)
        matched = regular.join(avid_ssids, on="SSID", how="inner")

        source_rows.extend(
            [
                {
                    "cohort_year": cohort_year,
                    "report_year": report_year,
                    "source_kind": "CALPADS_311_AVID_COURSE",
                    "source_uri": f"s3://{bucket}/{course_key}",
                    "source_rows": course.height,
                    "source_unique_ssids": course.get_column("SSID").n_unique(),
                    "qualifying_rows": avid_course.height,
                    "qualifying_unique_ssids": avid_ssids.height,
                    "matched_avid_graduates": matched.height,
                    "object_bytes": len(course_payload),
                    "etag": str(course_response.get("ETag", "")).strip('"'),
                    "sha256": hashlib.sha256(course_payload).hexdigest(),
                },
                {
                    "cohort_year": cohort_year,
                    "report_year": report_year,
                    "source_kind": "CALPADS_152_REGULAR_GRADUATE",
                    "source_uri": f"s3://{bucket}/{graduate_key}",
                    "source_rows": graduate.height,
                    "source_unique_ssids": graduate.get_column("SSID").n_unique(),
                    "qualifying_rows": regular.height,
                    "qualifying_unique_ssids": regular.height,
                    "matched_avid_graduates": matched.height,
                    "object_bytes": len(graduate_payload),
                    "etag": str(graduate_response.get("ETag", "")).strip('"'),
                    "sha256": hashlib.sha256(graduate_payload).hexdigest(),
                },
            ]
        )
        cohort_rows.append(
            {
                "cohort_year": cohort_year,
                "report_year": report_year,
                "course_rows": course.height,
                "avid_course_rows": avid_course.height,
                "avid_course_unique_ssids": avid_ssids.height,
                "regular_graduates": regular.height,
                "matched_avid_graduates": matched.height,
                "duplicate_regular_graduate_rows": int(
                    duplicates.get_column("GraduateRows").sum() - duplicates.height
                )
                if not duplicates.is_empty()
                else 0,
            }
        )
        matched_frames.append(matched)
        duplicate_frames.append(duplicates)

    all_matched = pl.concat(matched_frames, how="vertical")
    cross_cohort = all_matched.group_by("SSID").agg(
        pl.col("CohortYear").n_unique().alias("CohortYears")
    ).filter(pl.col("CohortYears") > 1)
    if not cross_cohort.is_empty():
        raise ValueError(
            f"AVID cohort conflict: {cross_cohort.height} SSIDs occur in multiple classes"
        )
    return (
        all_matched.sort(["CohortYear", "SSID"]),
        pl.DataFrame(source_rows).sort(["cohort_year", "source_kind"]),
        pl.DataFrame(cohort_rows).sort("cohort_year"),
        pl.concat(duplicate_frames, how="vertical").sort(["CohortYear", "SSID"]),
    )


def generate(args: argparse.Namespace) -> dict[str, object]:
    run_date = date.fromisoformat(
        f"{args.run_date[:4]}-{args.run_date[4:6]}-{args.run_date[6:]}"
    ).strftime("%Y%m%d")
    cohort_years = parse_cohort_years(args.cohort_years or DEFAULT_COHORT_YEARS)
    client = boto3.Session(profile_name=args.profile).client("s3")
    graduates, source_manifest, cohort_source_summary, graduate_duplicates = (
        load_avid_cohorts(client, args.bucket, args.prefix, cohort_years)
    )
    if graduates.is_empty():
        raise ValueError("No AVID students matched the configured multi-class cohort")
    ready, blockers, candidates = request_contract.enrich_and_classify(
        graduates,
        request_contract.read_account_refs(args.account_refs),
        request_contract.read_sinf(args.sinf),
    )
    if candidates.height != ready.height + blockers.height:
        raise AssertionError("Ready/blocker reconciliation failed")
    if ready.get_column("SSID").n_unique() != ready.height:
        raise AssertionError("Duplicate outbound AVID SSID exists")
    if ready.is_empty():
        raise ValueError("All AVID candidates were blocked")

    cohort_summary = cohort_source_summary.join(
        blockers.group_by("CohortYear").agg(pl.len().alias("blocked_rows")),
        left_on="cohort_year",
        right_on="CohortYear",
        how="left",
    ).join(
        ready.group_by("CohortYear").agg(pl.len().alias("outbound_students")),
        left_on="cohort_year",
        right_on="CohortYear",
        how="left",
    ).with_columns(
        pl.col("blocked_rows").fill_null(0),
        pl.col("outbound_students").fill_null(0),
    ).sort("cohort_year")

    result = {
        "mode": "preflight" if args.preflight_only else "write",
        "run_date": run_date,
        "cohort_years": list(cohort_years),
        "source_files": source_manifest.height,
        "source_rows": int(source_manifest.get_column("source_rows").sum()),
        "matched_avid_graduates": graduates.height,
        "blocked_rows": blockers.height,
        "outbound_students": ready.height,
        "service_accounts": ready.get_column("SA").n_unique(),
        "cohort_summary": cohort_summary.select(
            "cohort_year",
            "avid_course_unique_ssids",
            "regular_graduates",
            "matched_avid_graduates",
            "blocked_rows",
            "outbound_students",
        ).to_dicts(),
        "blocker_reason_summary": blockers.group_by(
            "CohortYear", "BlockerReasons"
        ).agg(pl.len().alias("rows")).sort(
            "CohortYear", "rows", descending=[False, True]
        ).to_dicts(),
    }
    if args.preflight_only:
        print(json.dumps(result, indent=2))
        return result

    audit_prefix = args.audit_dir / f"{run_date}_avid_request"
    audit_paths = {
        "source": Path(f"{audit_prefix}_source_manifest.csv"),
        "duplicates": Path(f"{audit_prefix}_graduate_duplicates.csv"),
        "blockers": Path(f"{audit_prefix}_blockers.csv"),
        "cohorts": Path(f"{audit_prefix}_cohort_summary.csv"),
        "summary": Path(f"{audit_prefix}_summary.csv"),
        "manifest": Path(f"{audit_prefix}_manifest.csv"),
        "upload": Path(f"{audit_prefix}_upload_manifest.csv"),
    }
    groups = ready.partition_by(["SA", "District"], as_dict=True)
    planned: list[Path] = []
    for key in groups:
        sa, district = (str(value) for value in key)
        filename = (
            f"{run_date}_{sa}_{request_contract.safe_filename_token(district)}_AVID.txt"
        )
        planned.extend((args.output_dir / filename, args.test_dir / filename))
    if not args.overwrite:
        existing = [path for path in [*audit_paths.values(), *planned] if path.exists()]
        if existing:
            raise FileExistsError(
                f"Refusing to overwrite {len(existing)} existing AVID outputs"
            )

    request_contract.write_csv_atomic(source_manifest, audit_paths["source"], args.overwrite)
    request_contract.write_csv_atomic(
        graduate_duplicates, audit_paths["duplicates"], args.overwrite
    )
    request_contract.write_csv_atomic(
        blockers.select(
            "SSID",
            "DistrictCode",
            "SchoolCode",
            "CDS",
            "SA",
            "District",
            "CohortYear",
            "SourceReportYear",
            "BlockerReasons",
        ),
        audit_paths["blockers"],
        args.overwrite,
    )
    request_contract.write_csv_atomic(
        cohort_summary, audit_paths["cohorts"], args.overwrite
    )

    manifest_rows: list[dict[str, object]] = []
    for key in sorted(groups, key=lambda value: tuple(str(item) for item in value)):
        sa, district = (str(value) for value in key)
        group = groups[key].sort(["CohortYear", "SSID"])
        observed_years = tuple(
            sorted(group.get_column("CohortYear").unique().to_list())
        )
        body = [
            request_contract.request_body_row(row)
            for row in group.iter_rows(named=True)
        ]
        header = [[
            "H3", sa, "", request_contract.sanitize_text(district), run_date, "SE", "D"
        ]]
        filename = (
            f"{run_date}_{sa}_{request_contract.safe_filename_token(district)}_AVID.txt"
        )
        request_path = args.output_dir / filename
        request_contract.write_tsv_atomic(
            request_path,
            header + body + [["T3", str(len(body) + 2)]],
            args.overwrite,
        )
        validation = request_contract.validate_request_file(
            request_path, sa, len(body), run_date
        )
        test_body = body[: min(len(body), 800)]
        test_path = args.test_dir / filename
        request_contract.write_tsv_atomic(
            test_path,
            header + test_body + [["T3", str(len(test_body) + 2)]],
            args.overwrite,
        )
        request_contract.validate_request_file(
            test_path, sa, len(test_body), run_date
        )
        manifest_rows.append(
            {
                "student_group": "AVID",
                "service_account": sa,
                "district": district,
                "cohort_years": "|".join(str(year) for year in cohort_years),
                "cohort_year_count": len(cohort_years),
                "observed_cohort_years": "|".join(
                    str(year) for year in observed_years
                ),
                "observed_cohort_year_count": len(observed_years),
                **validation,
            }
        )

    manifest = pl.DataFrame(manifest_rows).sort("district", "service_account")
    request_contract.write_csv_atomic(manifest, audit_paths["manifest"], args.overwrite)
    request_contract.write_csv_atomic(manifest, audit_paths["upload"], args.overwrite)
    summary = pl.DataFrame(
        [
            {
                "run_date": run_date,
                "cohort_years": "|".join(str(year) for year in cohort_years),
                "cohort_year_count": len(cohort_years),
                "source_files": source_manifest.height,
                "source_rows": int(source_manifest.get_column("source_rows").sum()),
                "matched_avid_graduates": candidates.height,
                "blocked_rows": blockers.height,
                "outbound_students": ready.height,
                "service_accounts": ready.get_column("SA").n_unique(),
                "request_files": manifest.height,
                "test_files": manifest.height,
                "upload_bytes": int(manifest.get_column("byte_size").sum()),
                "account_ref_file": str(args.account_refs),
                "account_ref_file_sha256": hashlib.sha256(
                    args.account_refs.read_bytes()
                ).hexdigest(),
                "sinf_file": str(args.sinf),
                "sinf_file_sha256": hashlib.sha256(args.sinf.read_bytes()).hexdigest(),
            }
        ]
    )
    request_contract.write_csv_atomic(summary, audit_paths["summary"], args.overwrite)
    result.update(
        {
            "request_files": manifest.height,
            "test_files": manifest.height,
            "manifest": str(audit_paths["manifest"]),
            "upload_manifest": str(audit_paths["upload"]),
            "summary": str(audit_paths["summary"]),
        }
    )
    print(json.dumps(result, indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--cohort-years")
    parser.add_argument("--profile", default=os.environ.get("ENV", "prod"))
    parser.add_argument("--bucket", default="example-studenttracker-bucket")
    parser.add_argument(
        "--prefix", default="calpads-snap/county=33/district=00000"
    )
    parser.add_argument(
        "--account-refs", type=Path, default=Path("data/account_refs.xlsx")
    )
    parser.add_argument(
        "--sinf", type=Path, default=Path("data/sinf_merge.parquet")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("requestfiles"))
    parser.add_argument(
        "--test-dir", type=Path, default=Path("requestfiles/test_file")
    )
    parser.add_argument("--audit-dir", type=Path, default=Path("audit"))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
