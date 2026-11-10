#!/usr/bin/env python3
# CTE generator: combine the declared classes from CTE-filtered annual snapshots and reconcile source, blocker, and outbound counts. REQ-27.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
"""Build countywide multi-class CTE StudentTracker request files.

The cohort comes from annual CALPADS 15.2 Account extracts filtered by CALPADS
to ``CTE Completer = Y``. The default request combines Classes 2023 through
2025, while preserving each student's graduation year and routing through the
current account references. MinIO is read-only; student-level values are never
printed to stdout.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
import warnings
from datetime import date, datetime
from pathlib import Path

import boto3
import polars as pl

from studenttracker_scope import parse_year_expression, validate_request_cohort_years


REQUEST_FIELD_COUNT = 25
DEFAULT_COHORT_YEARS = "2023-2025"
CTE_COHORT_REQUIRED_COLUMNS = (
    "DistrictCode", "SchoolCode", "SSID", "StudentCompletionStatus",
    "CohortCategory", "BirthDate", "StudentEnrollmentExitDate",
    "Gender", "EthnicityRace", "MigrantEd", "StudentswithDisabilities",
    "SocioEconomicallyDisadvantaged", "EnglishLearner", "FosterYouth",
    "Homeless", "Sealofbiliteracy", "UC_CSURequirementsMet",
)
EXPECTED_DEMOGRAPHIC_COLUMNS = (
    "Gender", "EthnicityRace", "MigrantEd", "StudentswithDisabilities",
    "SocioEconomicallyDisadvantaged", "EnglishLearner", "FosterYouth",
    "Homeless", "Sealofbiliteracy", "UC_CSURequirementsMet",
)
SUPPRESSED_RCOE_CHARTER_ACTS = {"054763", "054113", "050558"}
MISSING_TEXT_TOKENS = {"NA", "N/A", "NULL", "Null", "null", "NONE", "None", "none"}


def normalize_scalar(value: object, width: int | None = None) -> str:
    text = "" if value is None else str(value).strip()
    if text in MISSING_TEXT_TOKENS:
        text = ""
    text = re.sub(r"\.0$", "", text)
    if width and text.isdigit():
        text = text.zfill(width)
    return text


def sanitize_text(value: object, *, optional: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if optional and text in MISSING_TEXT_TOKENS:
        text = ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\t\r\n]+", " ", text).replace(".", "").strip()


def safe_filename_token(value: object) -> str:
    return re.sub(r"[^A-Z0-9-]+", "", sanitize_text(value).upper())


def normalize_expr(column: str, width: int | None = None) -> pl.Expr:
    expr = (
        pl.col(column).cast(pl.String).fill_null("").str.strip_chars()
        .str.replace(r"\.0$", "")
    )
    expr = pl.when(expr.is_in(sorted(MISSING_TEXT_TOKENS))).then(
        pl.lit("")
    ).otherwise(expr)
    if width:
        expr = pl.when(expr.str.contains(r"^\d+$")).then(expr.str.zfill(width)).otherwise(expr)
    return expr


def parse_date_expr(column: str) -> pl.Expr:
    raw = pl.col(column).cast(pl.String).fill_null("").str.strip_chars()
    return pl.coalesce(
        raw.str.to_date("%Y-%m-%d", strict=False),
        raw.str.to_date("%m/%d/%Y", strict=False),
        raw.str.to_date("%Y%m%d", strict=False),
    )


def parse_cohort_years(value: str) -> tuple[int, ...]:
    years = parse_year_expression(value)
    return validate_request_cohort_years(
        years, minimum=3, context="CTE request batch"
    )


def cte_cohort_source_key(prefix: str, cohort_year: int) -> str:
    report_year = f"{cohort_year - 1}-{cohort_year}"
    return f"{prefix.rstrip('/')}/year={cohort_year}/{report_year}_152_account_cte.parquet"


def load_cte_cohorts(
    client: object, bucket: str, prefix: str, cohort_years: tuple[int, ...]
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    graduate_frames: list[pl.DataFrame] = []
    duplicate_frames: list[pl.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    for cohort_year in cohort_years:
        report_year = f"{cohort_year - 1}-{cohort_year}"
        key = cte_cohort_source_key(prefix, cohort_year)
        response = client.get_object(Bucket=bucket, Key=key)
        payload = response["Body"].read()
        try:
            frame = pl.read_parquet(
                io.BytesIO(payload), columns=list(CTE_COHORT_REQUIRED_COLUMNS)
            )
        except Exception as exc:
            raise ValueError(f"15.2 CTE schema/read failure for s3://{bucket}/{key}") from exc
        frame = frame.with_columns(
            normalize_expr("SSID").alias("SSID"),
            normalize_expr("DistrictCode", 7).alias("DistrictCode"),
            normalize_expr("SchoolCode", 7).alias("SchoolCode"),
            normalize_expr("StudentCompletionStatus").alias("StudentCompletionStatus"),
            normalize_expr("CohortCategory").alias("CohortCategory"),
            parse_date_expr("BirthDate").alias("BirthDateParsed"),
            parse_date_expr("StudentEnrollmentExitDate").alias("ExitDateParsed"),
        ).with_columns(pl.concat_str("DistrictCode", "SchoolCode").alias("CDS"))
        frame = frame.with_columns(
            pl.when(pl.col("CDS") == "01252370125237")
            .then(pl.lit("33103300125237"))
            .otherwise(pl.col("CDS")).alias("CDS")
        )
        invalid = frame.filter(~pl.col("SSID").str.contains(r"^\d{10}$"))
        if not invalid.is_empty():
            raise ValueError(
                f"15.2 CTE identifier drift for s3://{bucket}/{key}: "
                f"{invalid.height} invalid SSID rows"
            )
        graduates = frame.filter(
            (pl.col("StudentCompletionStatus") == "100")
            & (pl.col("CohortCategory") == "HSDiplomaGraduate")
        ).with_columns(
            pl.lit(cohort_year).alias("CohortYear"),
            pl.lit(report_year).alias("SourceReportYear"),
            pl.lit(date(cohort_year - 1, 9, 1)).alias("GraduationWindowStart"),
            pl.lit(date(cohort_year, 8, 31)).alias("GraduationWindowEnd"),
        )
        duplicates = graduates.group_by("SSID").agg(
            pl.len().alias("GraduateRows"),
            pl.col("CDS").n_unique().alias("DistinctCDS"),
        ).filter(pl.col("GraduateRows") > 1).with_columns(
            pl.lit(cohort_year).alias("CohortYear"),
            pl.lit(report_year).alias("SourceReportYear"),
        ).select(
            "CohortYear", "SourceReportYear", "SSID", "GraduateRows", "DistinctCDS"
        ).sort("SSID")
        graduates = graduates.sort(
            ["SSID", "ExitDateParsed", "CDS"],
            descending=[False, True, False], nulls_last=True,
        ).unique(subset=["SSID"], keep="first", maintain_order=True)
        summary_rows.append(
            {
                "report_year": report_year,
                "cohort_year": cohort_year,
                "source_uri": f"s3://{bucket}/{key}",
                "source_rows": frame.height,
                "source_unique_ssids": frame.get_column("SSID").n_unique(),
                "regular_graduates": graduates.height,
                "duplicate_regular_graduate_rows": int(
                    duplicates.get_column("GraduateRows").sum() - duplicates.height
                ) if not duplicates.is_empty() else 0,
                "school_codes": frame.get_column("SchoolCode").n_unique(),
                "district_codes": frame.get_column("DistrictCode").n_unique(),
                "object_bytes": len(payload),
                "etag": str(response.get("ETag", "")).strip('"'),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        graduate_frames.append(graduates)
        duplicate_frames.append(duplicates)
    all_graduates = pl.concat(graduate_frames, how="vertical")
    cross_cohort = all_graduates.group_by("SSID").agg(
        pl.col("CohortYear").n_unique().alias("CohortYears")
    ).filter(pl.col("CohortYears") > 1)
    if not cross_cohort.is_empty():
        raise ValueError(
            f"15.2 CTE cohort conflict: {cross_cohort.height} SSIDs occur in multiple classes"
        )
    return (
        all_graduates.sort(["CohortYear", "SSID"]),
        pl.DataFrame(summary_rows).sort("cohort_year"),
        pl.concat(duplicate_frames, how="vertical").sort(["CohortYear", "SSID"]),
    )


def read_account_refs(path: Path) -> pl.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"from_arrow\(<ArrowStreamExportable>\) will return a Series",
            category=FutureWarning,
        )
        refs = pl.read_excel(path, engine="calamine")
    required = {"CDS", "SA", "ACT", "District", "HSName"}
    missing = sorted(required - set(refs.columns))
    if missing:
        raise ValueError(f"Account-reference schema drift: missing {missing}")
    refs = (
        refs.select("CDS", "SA", "ACT", "District", "HSName").with_columns(
            normalize_expr("CDS", 14).alias("CDS"),
            normalize_expr("SA", 8).alias("SA"),
            normalize_expr("ACT", 6).alias("ACT"),
            pl.col("District").cast(pl.String).fill_null("").str.strip_chars(),
            pl.col("HSName").cast(pl.String).fill_null("").str.strip_chars(),
        ).filter(pl.col("CDS") != "")
    )
    conflicts = refs.group_by("CDS").agg(
        pl.struct("SA", "ACT", "District", "HSName").n_unique().alias("n")
    ).filter(pl.col("n") > 1)
    if not conflicts.is_empty():
        raise ValueError("Conflicting CDS mappings exist in account_refs.xlsx")
    return refs.unique(subset=["CDS"], keep="first")


def read_sinf(path: Path) -> pl.DataFrame:
    schema = pl.scan_parquet(path).collect_schema()
    required = {
        "SSID", "DistrictCode", "SchoolCode", "FirstName", "MiddleName",
        "LastName", "Suffix", "ModifyDate",
    }
    missing = sorted(required - set(schema.names()))
    if missing:
        raise ValueError(f"SINF schema drift: missing {missing}")
    sinf = pl.read_parquet(path, columns=sorted(required)).with_columns(
        normalize_expr("SSID").alias("SSID"),
        normalize_expr("DistrictCode", 7).alias("SinfDistrictCode"),
        normalize_expr("SchoolCode", 7).alias("SinfSchoolCode"),
        *[
            pl.col(column).cast(pl.String).fill_null("").alias(column)
            for column in ("FirstName", "MiddleName", "LastName", "Suffix", "ModifyDate")
        ],
    )
    return (
        sinf.sort("ModifyDate", descending=True)
        .unique(subset=["SinfDistrictCode", "SSID"], keep="first")
        .with_columns(
            *[
                pl.col(column).map_elements(
                    lambda value, optional=column in {"MiddleName", "Suffix"}: sanitize_text(
                        value, optional=optional
                    ),
                    return_dtype=pl.String,
                ).alias(column)
                for column in ("FirstName", "MiddleName", "LastName", "Suffix")
            ]
        )
    )


def enrich_and_classify(
    graduates: pl.DataFrame,
    refs: pl.DataFrame,
    sinf: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    candidates = graduates
    if candidates.is_empty():
        raise ValueError("No regular graduates found in the configured 15.2 CTE cohorts")
    for column in EXPECTED_DEMOGRAPHIC_COLUMNS:
        if candidates.filter(
            pl.col(column).cast(pl.String).fill_null("").str.strip_chars() != ""
        ).is_empty():
            raise ValueError(f"Demographic schema drift: all candidate values blank for {column}")
    sinf_district_codes = sinf.get_column("SinfDistrictCode").unique()
    candidates = (
        candidates.with_columns(
            pl.when(pl.col("SchoolCode").is_in(sinf_district_codes.implode()))
            .then(pl.col("SchoolCode")).otherwise(pl.col("DistrictCode"))
            .alias("SinfJoinCode")
        ).join(refs, on="CDS", how="left").join(
            sinf.select(
                "SSID", pl.col("SinfDistrictCode").alias("SinfJoinCode"),
                "FirstName", "MiddleName", "LastName", "Suffix",
            ),
            on=["SSID", "SinfJoinCode"], how="left",
        ).with_columns(
            *[
                pl.col(column).fill_null("").alias(column)
                for column in (
                    "SA", "ACT", "District", "HSName", "FirstName",
                    "MiddleName", "LastName", "Suffix",
                )
            ]
        )
    )
    reasons = pl.concat_str(
        pl.when(~pl.col("SSID").str.contains(r"^\d{10}$")).then(pl.lit("invalid_ssid; ")).otherwise(pl.lit("")),
        pl.when(pl.col("FirstName") == "").then(pl.lit("missing_first_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("LastName") == "").then(pl.lit("missing_last_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("BirthDateParsed").is_null()).then(pl.lit("missing_or_invalid_birth_date; ")).otherwise(pl.lit("")),
        pl.when(pl.col("ExitDateParsed").is_null()).then(pl.lit("missing_or_invalid_exit_date; ")).otherwise(pl.lit("")),
        pl.when(
            pl.col("ExitDateParsed").is_not_null()
            & ~pl.col("ExitDateParsed").is_between(
                pl.col("GraduationWindowStart"),
                pl.col("GraduationWindowEnd"),
                closed="both",
            )
        ).then(pl.lit("outside_class_graduation_window; ")).otherwise(pl.lit("")),
        pl.when(pl.col("SA") == "").then(pl.lit("missing_service_account; ")).otherwise(pl.lit("")),
        pl.when(pl.col("ACT") == "").then(pl.lit("missing_act; ")).otherwise(pl.lit("")),
        pl.when(pl.col("District") == "").then(pl.lit("missing_district_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("HSName") == "").then(pl.lit("missing_high_school_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("ACT").is_in(sorted(SUPPRESSED_RCOE_CHARTER_ACTS))).then(pl.lit("suppressed_rcoe_charter; ")).otherwise(pl.lit("")),
        pl.when((pl.col("ACT") != "") & (pl.col("ACT").str.len_chars() != 6)).then(pl.lit("invalid_act_length; ")).otherwise(pl.lit("")),
        pl.when(pl.col("FirstName").str.len_chars() > 40).then(pl.lit("first_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("MiddleName").str.len_chars() > 40).then(pl.lit("middle_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("LastName").str.len_chars() > 40).then(pl.lit("last_name_too_long; ")).otherwise(pl.lit("")),
        pl.when((pl.col("Suffix") != "") & ~pl.col("Suffix").str.contains(r"^[A-Za-z]{1,3}$")).then(pl.lit("invalid_suffix; ")).otherwise(pl.lit("")),
    ).str.strip_chars("; ")
    candidates = candidates.with_columns(reasons.alias("BlockerReasons"))
    return (
        candidates.filter(pl.col("BlockerReasons") == ""),
        candidates.filter(pl.col("BlockerReasons") != ""),
        candidates,
    )


def yes_no(value: object) -> str:
    token = normalize_scalar(value).upper()
    if token in {"YES", "Y", "TRUE", "1"}:
        return "Y"
    if token in {"NO", "N", "FALSE", "0"}:
        return "N"
    return ""


def race_code(value: object) -> str:
    return {
        "AFRICAN AMERICAN": "BL", "ASIAN": "AS", "FILIPINO": "AS",
        "NATIVE AMERICAN": "AM", "PACIFIC ISLANDER": "PI",
        "TWO OR MORE": "MU", "WHITE": "WH", "HISPANIC": "HI",
    }.get(normalize_scalar(value).upper(), "")


def program_codes(row: dict[str, object]) -> str:
    return ".".join(
        (
            f"MIG_{yes_no(row['MigrantEd']) or 'N'}",
            f"FOS_{yes_no(row['FosterYouth']) or 'N'}",
            f"HOM_{yes_no(row['Homeless']) or 'N'}",
            f"AG_{yes_no(row['UC_CSURequirementsMet']) or 'N'}",
            f"SSB_{yes_no(row['Sealofbiliteracy']) or 'N'}",
        )
    )


def request_body_row(row: dict[str, object]) -> list[str]:
    fields = [
        "D3", "", sanitize_text(row["FirstName"]),
        sanitize_text(row["MiddleName"], optional=True), sanitize_text(row["LastName"]),
        sanitize_text(row["Suffix"], optional=True),
        row["BirthDateParsed"].strftime("%Y%m%d"),
        row["ExitDateParsed"].strftime("%Y%m%d"), normalize_scalar(row["ACT"], 6),
        "", "", normalize_scalar(row["SSID"]),
        normalize_scalar(row["Gender"]).upper()
        if normalize_scalar(row["Gender"]).upper() in {"M", "F"} else "",
        race_code(row["EthnicityRace"]), yes_no(row["SocioEconomicallyDisadvantaged"]),
        "", "", "", "", yes_no(row["EnglishLearner"]), "", "",
        yes_no(row["StudentswithDisabilities"]), program_codes(row), "ED",
    ]
    if len(fields) != REQUEST_FIELD_COUNT:
        raise AssertionError("Internal request body width mismatch")
    return fields


def write_tsv_atomic(path: Path, rows: list[list[str]], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing request file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent,
        prefix=f".{path.name}.", delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        csv.writer(
            handle, delimiter="\t", lineterminator="\n",
            quoting=csv.QUOTE_NONE, escapechar="\\",
        ).writerows(rows)
    if path.exists() and overwrite:
        path.unlink()
    os.replace(temp_path, path)


def write_csv_atomic(frame: pl.DataFrame, path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing audit file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temp_path = Path(handle.name)
    frame.write_csv(temp_path)
    if path.exists() and overwrite:
        path.unlink()
    os.replace(temp_path, path)


def validate_request_file(
    path: Path, expected_sa: str, expected_body_rows: int, expected_run_date: str
) -> dict[str, object]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    if not rows or rows[0][0] != "H3" or rows[-1][0] != "T3":
        raise ValueError(f"Invalid H3/T3 envelope: {path}")
    if len(rows[0]) != 7 or rows[0][1] != expected_sa or rows[0][4] != expected_run_date:
        raise ValueError(f"Invalid request header: {path}")
    if len(rows) != expected_body_rows + 2 or int(rows[-1][1]) != len(rows):
        raise ValueError(f"Trailer count mismatch: {path}")
    for row in rows[1:-1]:
        if len(row) != REQUEST_FIELD_COUNT or row[0] != "D3":
            raise ValueError(f"Invalid D3 row width/type: {path}")
        if any(not row[index] for index in (2, 4, 6, 7, 8, 11)):
            raise ValueError(f"Missing required D3 value: {path}")
        if not re.fullmatch(r"\d{10}", row[11]):
            raise ValueError(f"Invalid raw SSID: {path}")
        if any(row[index].strip() in MISSING_TEXT_TOKENS for index in (3, 5)):
            raise ValueError(f"Missing-value placeholder in optional name field: {path}")
        limits = {2: 40, 3: 40, 4: 40, 5: 3, 8: 6, 11: 15, 23: 50}
        if any(len(row[index]) > maximum for index, maximum in limits.items()):
            raise ValueError(f"D3 value exceeds vendor length limit: {path}")
    payload = path.read_bytes()
    return {
        "local_path": str(path), "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "student_rows": expected_body_rows, "total_lines": len(rows),
    }


def generate(args: argparse.Namespace) -> dict[str, object]:
    run_date = datetime.strptime(args.run_date, "%Y%m%d").strftime("%Y%m%d")
    cohort_years = parse_cohort_years(args.cohort_years or DEFAULT_COHORT_YEARS)
    client = boto3.Session(profile_name=args.profile).client("s3")
    graduates, source_summary, graduate_duplicates = load_cte_cohorts(
        client, args.bucket, args.prefix, cohort_years
    )
    ready, blockers, candidates = enrich_and_classify(
        graduates, read_account_refs(args.account_refs), read_sinf(args.sinf)
    )
    if candidates.height != ready.height + blockers.height:
        raise AssertionError("Ready/blocker reconciliation failed")
    if ready.get_column("SSID").n_unique() != ready.height:
        raise AssertionError("Duplicate outbound CTE SSID exists")
    if ready.is_empty():
        raise ValueError("All CTE candidates were blocked")

    cohort_summary = (
        source_summary.select(
            "cohort_year", "report_year", "source_uri", "source_rows",
            "source_unique_ssids", "regular_graduates",
        )
        .join(
            blockers.group_by("CohortYear").agg(pl.len().alias("blocked_rows")),
            left_on="cohort_year", right_on="CohortYear", how="left",
        )
        .join(
            ready.group_by("CohortYear").agg(pl.len().alias("outbound_students")),
            left_on="cohort_year", right_on="CohortYear", how="left",
        )
        .with_columns(
            pl.col("blocked_rows").fill_null(0),
            pl.col("outbound_students").fill_null(0),
        )
        .sort("cohort_year")
    )
    result = {
        "mode": "preflight" if args.preflight_only else "write",
        "run_date": run_date,
        "cohort_years": list(cohort_years),
        "source_files": source_summary.height,
        "source_rows": int(source_summary.get_column("source_rows").sum()),
        "class_regular_graduates": graduates.height,
        "blocked_rows": blockers.height,
        "outbound_students": ready.height,
        "service_accounts": ready.get_column("SA").n_unique(),
        "cohort_summary": cohort_summary.select(
            "cohort_year", "regular_graduates", "blocked_rows", "outbound_students"
        ).to_dicts(),
        "blocker_reason_summary": blockers.group_by(
            "CohortYear", "BlockerReasons"
        ).agg(
            pl.len().alias("rows")
        ).sort(
            "CohortYear", "rows", descending=[False, True]
        ).to_dicts(),
    }
    if args.preflight_only:
        print(json.dumps(result, indent=2))
        return result

    audit_prefix = args.audit_dir / f"{run_date}_cte_request"
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
    planned_requests: list[Path] = []
    for key in groups:
        sa, district = (str(value) for value in key)
        filename = f"{run_date}_{sa}_{safe_filename_token(district)}_CTE.txt"
        planned_requests.extend((args.output_dir / filename, args.test_dir / filename))
    if not args.overwrite:
        existing = [path for path in list(audit_paths.values()) + planned_requests if path.exists()]
        if existing:
            raise FileExistsError(f"Refusing to overwrite {len(existing)} existing CTE outputs")

    write_csv_atomic(source_summary, audit_paths["source"], args.overwrite)
    write_csv_atomic(graduate_duplicates, audit_paths["duplicates"], args.overwrite)
    write_csv_atomic(
        blockers.select(
            "SSID", "DistrictCode", "SchoolCode", "CDS", "SA", "District",
            "CohortYear", "SourceReportYear", "BlockerReasons",
        ),
        audit_paths["blockers"], args.overwrite,
    )
    write_csv_atomic(cohort_summary, audit_paths["cohorts"], args.overwrite)

    manifest_rows: list[dict[str, object]] = []
    for key in sorted(groups, key=lambda value: tuple(str(item) for item in value)):
        sa, district = (str(value) for value in key)
        group = groups[key].sort("SSID")
        observed_cohort_years = tuple(
            sorted(group.get_column("CohortYear").unique().to_list())
        )
        body = [request_body_row(row) for row in group.iter_rows(named=True)]
        header = [["H3", sa, "", sanitize_text(district), run_date, "SE", "D"]]
        filename = f"{run_date}_{sa}_{safe_filename_token(district)}_CTE.txt"
        request_path = args.output_dir / filename
        write_tsv_atomic(
            request_path, header + body + [["T3", str(len(body) + 2)]], args.overwrite
        )
        validation = validate_request_file(request_path, sa, len(body), run_date)
        test_body = body[: min(len(body), 800)]
        test_path = args.test_dir / filename
        write_tsv_atomic(
            test_path, header + test_body + [["T3", str(len(test_body) + 2)]], args.overwrite
        )
        validate_request_file(test_path, sa, len(test_body), run_date)
        manifest_rows.append(
            {
                "student_group": "CTE", "service_account": sa,
                "district": district,
                "cohort_years": "|".join(str(year) for year in cohort_years),
                "cohort_year_count": len(cohort_years),
                "observed_cohort_years": "|".join(
                    str(year) for year in observed_cohort_years
                ),
                "observed_cohort_year_count": len(observed_cohort_years),
                **validation,
            }
        )

    manifest = pl.DataFrame(manifest_rows).sort("district", "service_account")
    write_csv_atomic(manifest, audit_paths["manifest"], args.overwrite)
    write_csv_atomic(manifest, audit_paths["upload"], args.overwrite)
    summary = pl.DataFrame(
        [
            {
                "run_date": run_date,
                "cohort_years": "|".join(str(year) for year in cohort_years),
                "cohort_year_count": len(cohort_years),
                "source_files": source_summary.height,
                "source_rows": int(source_summary.get_column("source_rows").sum()),
                "class_regular_graduates": graduates.height,
                "matched_cte_graduates": candidates.height,
                "blocked_rows": blockers.height,
                "outbound_students": ready.height,
                "service_accounts": ready.get_column("SA").n_unique(),
                "request_files": manifest.height,
                "test_files": manifest.height,
                "upload_bytes": int(manifest.get_column("byte_size").sum()),
                "account_ref_file": str(args.account_refs),
                "account_ref_file_sha256": hashlib.sha256(args.account_refs.read_bytes()).hexdigest(),
                "sinf_file": str(args.sinf),
                "sinf_file_sha256": hashlib.sha256(args.sinf.read_bytes()).hexdigest(),
            }
        ]
    )
    write_csv_atomic(summary, audit_paths["summary"], args.overwrite)
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
    parser.add_argument("--prefix", default="calpads-snap/county=33/district=00000")
    parser.add_argument("--account-refs", type=Path, default=Path("data/account_refs.xlsx"))
    parser.add_argument("--sinf", type=Path, default=Path("data/sinf_merge.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("requestfiles"))
    parser.add_argument("--test-dir", type=Path, default=Path("requestfiles/test_file"))
    parser.add_argument("--audit-dir", type=Path, default=Path("audit"))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
