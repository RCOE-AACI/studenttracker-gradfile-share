#!/usr/bin/env python3
# CCR request generator and shared request helpers: keep deduplication within each program, then validate the 25-field contract. REQ-26.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
"""Build and validate multi-year CCR StudentTracker request files.

The four source families under ``data/ccrSummer2026`` are treated as separate
StudentTracker batches. Student-level blockers remain in the project-local
audit directory and are never printed to stdout.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

import polars as pl

from studenttracker_scope import validate_request_cohort_years


SOURCE_CLASSES = ("2122", "2223", "2324", "2425")
SOURCE_COHORT_YEARS = tuple(2000 + int(value[-2:]) for value in SOURCE_CLASSES)
PROGRAMS = ("AP", "CC", "IB", "SSB")
REQUIRED_SOURCE_COLUMNS = (
    "DistrictCode", "SchoolCode", "SSID", "Gender", "EthnicityRace",
    "BirthDate", "MigrantEd", "StudentswithDisabilities",
    "SocioEconomicallyDisadvantaged", "EnglishLearner", "FosterYouth",
    "Homeless", "Sealofbiliteracy", "UC_CSURequirementsMet",
    "StudentEnrollmentExitDate", "CDS Code",
)
EXPECTED_DEMOGRAPHIC_COLUMNS = (
    "Gender", "EthnicityRace", "MigrantEd", "StudentswithDisabilities",
    "SocioEconomicallyDisadvantaged", "EnglishLearner", "FosterYouth",
    "Homeless", "Sealofbiliteracy", "UC_CSURequirementsMet",
)
REQUEST_FIELD_COUNT = 25


def normalize_scalar(value: object, width: int | None = None) -> str:
    text = "" if value is None else str(value).strip()
    text = re.sub(r"\.0$", "", text)
    return text.zfill(width) if width and text else text


def sanitize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\t\r\n]+", " ", text).replace(".", "").strip()


def safe_filename_token(value: object) -> str:
    return re.sub(r"[^A-Z0-9-]+", "", sanitize_text(value).upper())


def normalize_expr(column: str, width: int | None = None) -> pl.Expr:
    expr = (
        pl.col(column).cast(pl.String).fill_null("").str.strip_chars()
        .str.replace(r"\.0$", "")
    )
    if not width:
        return expr
    return pl.when(expr == "").then(pl.lit("")).otherwise(expr.str.zfill(width))


def parse_source_date(column: str) -> pl.Expr:
    return (
        pl.col(column).cast(pl.String).fill_null("").str.strip_chars()
        .str.to_date("%m/%d/%Y", strict=False)
    )


def read_sources(input_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    frames: list[pl.DataFrame] = []
    summaries: list[dict[str, object]] = []
    for source_class in SOURCE_CLASSES:
        for program in PROGRAMS:
            path = input_dir / source_class / f"{program}{source_class}.csv"
            if not path.is_file():
                raise FileNotFoundError(f"Missing required CCR source: {path}")
            frame = pl.read_csv(
                path, infer_schema_length=0, encoding="utf8-lossy", try_parse_dates=False
            ).with_columns(pl.all().cast(pl.String).fill_null("").str.strip_chars())
            missing = sorted(set(REQUIRED_SOURCE_COLUMNS) - set(frame.columns))
            if missing:
                raise ValueError(f"{path} is missing required columns: {missing}")
            all_blank = [
                column for column in EXPECTED_DEMOGRAPHIC_COLUMNS
                if not frame.is_empty() and frame.filter(pl.col(column) != "").is_empty()
            ]
            if all_blank:
                raise ValueError(f"Demographic schema drift in {path}: all blank {all_blank}")
            frame = (
                frame.select(REQUIRED_SOURCE_COLUMNS)
                .with_columns(
                    normalize_expr("SSID").alias("SSID"),
                    normalize_expr("DistrictCode", 7).alias("DistrictCode"),
                    normalize_expr("SchoolCode", 7).alias("SchoolCode"),
                    normalize_expr("CDS Code", 14).alias("CDS"),
                    parse_source_date("BirthDate").alias("BirthDateParsed"),
                    parse_source_date("StudentEnrollmentExitDate").alias("ExitDateParsed"),
                    pl.lit(source_class).alias("SourceClass"),
                    pl.lit(program).alias("Program"),
                    pl.lit(str(path)).alias("SourceFile"),
                )
                .with_columns(
                    pl.when(pl.col("CDS") == "")
                    .then(pl.concat_str("DistrictCode", "SchoolCode"))
                    .otherwise(pl.col("CDS")).alias("CDS")
                )
                .with_columns(
                    pl.when(pl.col("CDS") == "01252370125237")
                    .then(pl.lit("33103300125237"))
                    .otherwise(pl.col("CDS")).alias("CDS")
                )
            )
            summaries.append({
                "program": program, "source_class": source_class,
                "source_file": str(path), "source_rows": frame.height,
                "unique_ssids": frame.get_column("SSID").n_unique(),
            })
            frames.append(frame)
    return pl.concat(frames, how="vertical"), pl.DataFrame(summaries)


def validate_ccr_request_scope(source_summary: pl.DataFrame) -> tuple[int, ...]:
    declared_years = validate_request_cohort_years(
        SOURCE_COHORT_YEARS, context="CCR request batch"
    )
    for program in PROGRAMS:
        populated_classes = source_summary.filter(
            (pl.col("program") == program) & (pl.col("source_rows") > 0)
        ).get_column("source_class").to_list()
        populated_years = tuple(2000 + int(value[-2:]) for value in populated_classes)
        validate_request_cohort_years(
            populated_years, context=f"CCR {program} request batch"
        )
    return declared_years


def read_account_refs(path: Path) -> pl.DataFrame:
    refs = pl.read_excel(path, engine="calamine").with_columns(
        normalize_expr("CDS", 14).alias("CDS"),
        normalize_expr("SA").alias("SA"),
        normalize_expr("ACT").alias("ACT"),
        pl.col("District").cast(pl.String).fill_null("").str.strip_chars(),
        pl.col("HSName").cast(pl.String).fill_null("").str.strip_chars(),
    ).filter(pl.col("CDS") != "")
    conflicts = (
        refs.group_by("CDS")
        .agg(pl.struct("SA", "ACT", "District", "HSName").n_unique().alias("n"))
        .filter(pl.col("n") > 1)
    )
    if not conflicts.is_empty():
        raise ValueError("Conflicting nonblank CDS mappings exist in account_refs.xlsx")
    return refs.unique(subset=["CDS"], keep="first")


def read_sinf(path: Path) -> pl.DataFrame:
    sinf = pl.scan_parquet(path).select(
        normalize_expr("SSID").alias("SSID"),
        normalize_expr("DistrictCode", 7).alias("SinfDistrictCode"),
        normalize_expr("SchoolCode", 7).alias("SinfSchoolCode"),
        *[
            pl.col(column).cast(pl.String).fill_null("").alias(column)
            for column in ("FirstName", "MiddleName", "LastName", "Suffix", "ModifyDate")
        ],
    ).collect()
    return (
        sinf.sort("ModifyDate", descending=True)
        .unique(subset=["SinfDistrictCode", "SSID"], keep="first")
        .with_columns([
            pl.col(column).map_elements(sanitize_text, return_dtype=pl.String).alias(column)
            for column in ("FirstName", "MiddleName", "LastName", "Suffix")
        ])
    )


def duplicate_audit_and_dedupe(source: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    duplicate_keys = (
        source.group_by("Program", "SSID").agg(pl.len().alias("SourceRows"))
        .filter(pl.col("SourceRows") > 1)
    )
    audit = (
        source.join(duplicate_keys, on=["Program", "SSID"], how="inner")
        .select("Program", "SSID", "SourceRows", "SourceClass", "SourceFile",
                "DistrictCode", "SchoolCode", "CDS")
        .sort("Program", "SSID", "SourceClass")
    )
    deduped = (
        source.sort(
            ["Program", "SSID", "SourceClass", "ExitDateParsed"],
            descending=[False, False, True, True], nulls_last=True,
        )
        .unique(subset=["Program", "SSID"], keep="first", maintain_order=True)
    )
    return audit, deduped


def enrich_and_classify(
    source: pl.DataFrame, refs: pl.DataFrame, sinf: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    sinf_codes = sinf.get_column("SinfDistrictCode").unique()
    enriched = (
        source.with_columns(
            pl.when(pl.col("SchoolCode").is_in(sinf_codes.implode()))
            .then(pl.col("SchoolCode")).otherwise(pl.col("DistrictCode"))
            .alias("SinfJoinCode")
        )
        .join(refs.select("CDS", "SA", "ACT", "District", "HSName"), on="CDS", how="left")
        .join(
            sinf.select(
                "SSID", pl.col("SinfDistrictCode").alias("SinfJoinCode"),
                "FirstName", "MiddleName", "LastName", "Suffix",
            ),
            on=["SSID", "SinfJoinCode"], how="left",
        )
        .with_columns([
            pl.col(column).fill_null("").alias(column)
            for column in ("SA", "ACT", "District", "HSName", "FirstName",
                           "MiddleName", "LastName", "Suffix")
        ])
    )
    reasons = pl.concat_str(
        pl.when(pl.col("SSID") == "").then(pl.lit("missing_ssid; ")).otherwise(pl.lit("")),
        pl.when(pl.col("FirstName") == "").then(pl.lit("missing_first_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("LastName") == "").then(pl.lit("missing_last_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("BirthDateParsed").is_null()).then(pl.lit("missing_or_invalid_birth_date; ")).otherwise(pl.lit("")),
        pl.when(pl.col("ExitDateParsed").is_null()).then(pl.lit("missing_or_invalid_exit_date; ")).otherwise(pl.lit("")),
        pl.when(pl.col("SA") == "").then(pl.lit("missing_service_account; ")).otherwise(pl.lit("")),
        pl.when(pl.col("ACT") == "").then(pl.lit("missing_act; ")).otherwise(pl.lit("")),
        pl.when(pl.col("District") == "").then(pl.lit("missing_district_name; ")).otherwise(pl.lit("")),
        pl.when(pl.col("FirstName").str.len_chars() > 40).then(pl.lit("first_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("MiddleName").str.len_chars() > 40).then(pl.lit("middle_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("LastName").str.len_chars() > 40).then(pl.lit("last_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(
            (pl.col("Suffix") != "") & ~pl.col("Suffix").str.contains(r"^[A-Za-z]{1,3}$")
        ).then(pl.lit("invalid_suffix; ")).otherwise(pl.lit("")),
        pl.when((pl.col("ACT") != "") & (pl.col("ACT").str.len_chars() != 6))
        .then(pl.lit("invalid_act_length; ")).otherwise(pl.lit("")),
        pl.when(pl.col("SA").str.len_chars() > 10).then(pl.lit("service_account_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("District").str.len_chars() > 80).then(pl.lit("district_name_too_long; ")).otherwise(pl.lit("")),
        pl.when(pl.col("SSID").str.len_chars() > 15).then(pl.lit("ssid_too_long; ")).otherwise(pl.lit("")),
    ).str.strip_chars("; ")
    enriched = enriched.with_columns(reasons.alias("BlockerReasons"))
    return (
        enriched.filter(pl.col("BlockerReasons") == ""),
        enriched.filter(pl.col("BlockerReasons") != ""),
    )


def yes_no(value: object) -> str:
    token = normalize_scalar(value).upper()
    if token in {"YES", "Y", "TRUE", "1"}:
        return "Y"
    if token in {"NO", "N", "FALSE", "0"}:
        return "N"
    return ""


def race_code(value: object) -> str:
    mapping = {
        "AFRICAN AMERICAN": "BL", "ASIAN": "AS", "FILIPINO": "AS",
        "NATIVE AMERICAN": "AM", "PACIFIC ISLANDER": "PI",
        "TWO OR MORE": "MU", "WHITE": "WH", "HISPANIC": "HI",
    }
    return mapping.get(normalize_scalar(value).upper(), "")


def program_codes(row: dict[str, object]) -> str:
    seal = "Y" if row["Program"] == "SSB" else yes_no(row["Sealofbiliteracy"])
    return ".".join((
        f"MIG_{yes_no(row['MigrantEd']) or 'N'}",
        f"FOS_{yes_no(row['FosterYouth']) or 'N'}",
        f"HOM_{yes_no(row['Homeless']) or 'N'}",
        f"AG_{yes_no(row['UC_CSURequirementsMet']) or 'N'}",
        f"SSB_{seal or 'N'}",
    ))


def request_body_row(row: dict[str, object]) -> list[str]:
    birth_date, exit_date = row["BirthDateParsed"], row["ExitDateParsed"]
    fields = [
        "D3", "", sanitize_text(row["FirstName"]), sanitize_text(row["MiddleName"]),
        sanitize_text(row["LastName"]), sanitize_text(row["Suffix"]),
        birth_date.strftime("%Y%m%d"), exit_date.strftime("%Y%m%d"),
        normalize_scalar(row["ACT"]), "", "", normalize_scalar(row["SSID"]),
        normalize_scalar(row["Gender"]).upper()
        if normalize_scalar(row["Gender"]).upper() in {"M", "F"} else "",
        race_code(row["EthnicityRace"]), yes_no(row["SocioEconomicallyDisadvantaged"]),
        "", "", "", "", yes_no(row["EnglishLearner"]), "",
        "Y" if row["Program"] == "CC" else "",
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
        if not re.fullmatch(r"\d{8}", row[6]) or not re.fullmatch(r"\d{8}", row[7]):
            raise ValueError(f"Invalid D3 date: {path}")
        if row[11].startswith("_") or row[11].endswith("_"):
            raise ValueError(f"Locally-added underscore in outbound SSID: {path}")
        limits = {2: 40, 3: 40, 4: 40, 5: 3, 8: 6, 11: 15, 23: 50}
        if any(len(row[index]) > maximum for index, maximum in limits.items()):
            raise ValueError(f"D3 value exceeds vendor length limit: {path}")
        if row[5] and not re.fullmatch(r"[A-Za-z]{1,3}", row[5]):
            raise ValueError(f"Invalid D3 suffix: {path}")
    payload = path.read_bytes()
    return {
        "local_path": str(path), "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "student_rows": expected_body_rows, "total_lines": len(rows),
    }


def write_audit_csv(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(path)


def generate(args: argparse.Namespace) -> dict[str, object]:
    run_date = datetime.strptime(args.run_date, "%Y%m%d").strftime("%Y%m%d")
    source, source_summary = read_sources(args.input_dir)
    cohort_years = validate_ccr_request_scope(source_summary)
    duplicate_audit, deduped = duplicate_audit_and_dedupe(source)
    ready, blockers = enrich_and_classify(
        deduped, read_account_refs(args.account_refs), read_sinf(args.sinf)
    )
    if deduped.height != ready.height + blockers.height:
        raise AssertionError("Ready/blocker reconciliation failed")
    if not ready.group_by("Program", "SSID").len().filter(pl.col("len") > 1).is_empty():
        raise AssertionError("Duplicate outbound SSID exists within a CCR program family")
    if ready.is_empty():
        raise ValueError("No request-ready CCR rows")

    audit_prefix = args.audit_dir / f"{run_date}_ccr_summer"
    write_audit_csv(
        blockers.select(
            "Program", "SourceClass", "SourceFile", "DistrictCode", "SchoolCode",
            "CDS", "SSID", "BlockerReasons",
        ),
        Path(f"{audit_prefix}_blockers.csv"),
    )
    write_audit_csv(duplicate_audit, Path(f"{audit_prefix}_duplicates.csv"))

    grouped = ready.partition_by(["Program", "SA", "District"], as_dict=True)
    planned: list[Path] = []
    for key in grouped:
        program, sa, district = (str(value) for value in key)
        filename = f"{run_date}_{sa}_{safe_filename_token(district)}_CCR_{program}.txt"
        planned.extend((args.output_dir / filename, args.test_dir / filename))
    if not args.overwrite and any(path.exists() for path in planned):
        raise FileExistsError("Refusing to overwrite existing CCR request files")

    manifest_rows: list[dict[str, object]] = []
    for key in sorted(grouped, key=lambda value: tuple(str(item) for item in value)):
        program, sa, district = (str(value) for value in key)
        group = grouped[key].sort("SSID")
        observed_source_classes = tuple(
            sorted(group.get_column("SourceClass").unique().to_list())
        )
        body = [request_body_row(row) for row in group.iter_rows(named=True)]
        header = [["H3", sa, "", sanitize_text(district), run_date, "SE", "D"]]
        filename = f"{run_date}_{sa}_{safe_filename_token(district)}_CCR_{program}.txt"
        output_path = args.output_dir / filename
        write_tsv_atomic(output_path, header + body + [["T3", str(len(body) + 2)]], args.overwrite)
        validation = validate_request_file(output_path, sa, len(body), run_date)

        test_body = body[: min(len(body), 800)]
        test_path = args.test_dir / filename
        write_tsv_atomic(
            test_path, header + test_body + [["T3", str(len(test_body) + 2)]], args.overwrite
        )
        validate_request_file(test_path, sa, len(test_body), run_date)
        manifest_rows.append({
            "program": program,
            "service_account": sa,
            "district": district,
            "cohort_years": "|".join(str(year) for year in cohort_years),
            "cohort_year_count": len(cohort_years),
            "observed_source_classes": "|".join(observed_source_classes),
            "observed_source_class_count": len(observed_source_classes),
            **validation,
        })

    manifest = pl.DataFrame(manifest_rows).sort("program", "district")
    manifest_path = Path(f"{audit_prefix}_manifest.csv")
    write_audit_csv(manifest, manifest_path)
    program_summary = (
        source_summary.group_by("program").agg(
            pl.col("source_rows").sum(),
            pl.col("unique_ssids").sum().alias("within_file_unique_ssids"),
        )
        .join(
            deduped.group_by("Program").len(name="deduped_rows").rename({"Program": "program"}),
            on="program",
        )
        .join(
            blockers.group_by("Program").len(name="blocked_rows").rename({"Program": "program"}),
            on="program", how="left",
        )
        .join(
            ready.group_by("Program").agg(
                pl.len().alias("outbound_rows"), pl.col("SA").n_unique().alias("service_accounts"),
            ).rename({"Program": "program"}),
            on="program",
        )
        .join(manifest.group_by("program").len(name="request_files"), on="program")
        .with_columns(pl.col("blocked_rows").fill_null(0))
        .with_columns((pl.col("source_rows") - pl.col("deduped_rows")).alias("duplicate_rows_removed"))
        .sort("program")
    )
    summary_path = Path(f"{audit_prefix}_summary.csv")
    write_audit_csv(program_summary, summary_path)
    result = {
        "run_date": run_date, "source_rows": source.height, "deduped_rows": deduped.height,
        "duplicate_rows_removed": source.height - deduped.height,
        "blocked_rows": blockers.height, "outbound_rows": ready.height,
        "request_files": manifest.height, "test_files": manifest.height,
        "programs": program_summary.to_dicts(), "manifest": str(manifest_path),
        "summary": str(summary_path), "blockers": str(Path(f"{audit_prefix}_blockers.csv")),
        "duplicates": str(Path(f"{audit_prefix}_duplicates.csv")),
    }
    print(json.dumps(result, indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--input-dir", type=Path, default=Path("data/ccrSummer2026"))
    parser.add_argument("--account-refs", type=Path, default=Path("data/account_refs.xlsx"))
    parser.add_argument("--sinf", type=Path, default=Path("data/sinf_merge.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("requestfiles"))
    parser.add_argument("--test-dir", type=Path, default=Path("requestfiles/test_file"))
    parser.add_argument("--audit-dir", type=Path, default=Path("audit"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
