#!/usr/bin/env python3
# AVID audit utility: inspect field domains and contract validity without uploading files.
# Run from the project root; this sharing copy supplies no real student records or working credentials.

import argparse
import csv
import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


MISSING_TOKENS = {"NA", "N/A", "NULL", "Null", "null", "NONE", "None", "none"}
RACE_CODES = {"", "AM", "AS", "BL", "HI", "PI", "WH", "MU"}
YES_NO_CODES = {"", "Y", "N"}
PROGRAM_RE = re.compile(r"^MIG_[YN]\.FOS_[YN]\.HOM_[YN]\.AG_[YN]\.SSB_[YN]$")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def add_check(checks, name, count, details="", review=False):
    checks.append(
        {
            "check": name,
            "status": "REVIEW" if review and count else ("FAIL" if count else "PASS"),
            "count": count,
            "details": details,
        }
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        manifest = list(csv.DictReader(handle))

    start = datetime.strptime(args.window_start, "%Y-%m-%d").date()
    end = datetime.strptime(args.window_end, "%Y-%m-%d").date()
    checks = []
    rows = []
    manifest_errors = 0
    envelope_errors = 0
    field_count_errors = 0

    for item in manifest:
        path = Path(item["path"])
        payload = path.read_bytes()
        manifest_errors += len(payload) != int(item["bytes"])
        manifest_errors += hashlib.sha256(payload).hexdigest() != item["sha256"]
        lines = payload.decode("utf-8").splitlines()
        fields = [line.split("\t") for line in lines]
        header = fields[0]
        trailer = fields[-1]
        body = fields[1:-1]
        envelope_errors += not (
            len(header) == 7
            and header[0] == "H3"
            and header[1] == item["sa"]
            and header[2] == ""
            and header[4].isdigit()
            and len(header[4]) == 8
            and header[5:] == ["SE", "D"]
            and trailer == ["T3", str(len(lines))]
            and len(body) == int(item["student_count"])
        )
        field_count_errors += sum(len(row) != 25 for row in body)
        rows.extend(row for row in body if len(row) == 25)

    add_check(checks, "manifest_size_and_sha256", manifest_errors)
    add_check(checks, "header_trailer_and_row_counts", envelope_errors)
    add_check(checks, "detail_field_count_25", field_count_errors)
    add_check(checks, "detail_record_type_D3", sum(row[0] != "D3" for row in rows))
    add_check(checks, "required_first_last_names", sum(row[2] == "" or row[4] == "" for row in rows))
    add_check(
        checks,
        "optional_name_missing_placeholders",
        sum(row[3].strip() in MISSING_TOKENS or row[5].strip() in MISSING_TOKENS for row in rows),
    )
    add_check(
        checks,
        "name_field_lengths",
        sum(len(row[2]) > 40 or len(row[3]) > 40 or len(row[4]) > 40 or len(row[5]) > 3 for row in rows),
    )
    add_check(checks, "suffix_letters_only", sum(bool(row[5]) and not row[5].isalpha() for row in rows))
    add_check(
        checks,
        "name_character_review",
        sum(any(not (char.isalpha() or char in " '-") for char in row[index]) for row in rows for index in (2, 3, 4, 5)),
        "Count is field occurrences, not students; names are not written to this audit.",
        review=True,
    )

    birth_dates = [parse_date(row[6]) for row in rows]
    exit_dates = [parse_date(row[7]) for row in rows]
    add_check(checks, "birth_date_YYYYMMDD", sum(value is None for value in birth_dates))
    add_check(checks, "exit_date_YYYYMMDD", sum(value is None for value in exit_dates))
    add_check(
        checks,
        "exit_date_graduation_window",
        sum(value is not None and not (start <= value <= end) for value in exit_dates),
    )
    age_outliers = 0
    for birth, exit_date in zip(birth_dates, exit_dates):
        if birth is None or exit_date is None:
            continue
        age = (exit_date - birth).days / 365.2425
        age_outliers += not (14 <= age <= 25)
    add_check(checks, "graduate_age_outside_14_to_25", age_outliers, review=True)

    add_check(checks, "act_code_six_alphanumeric", sum(not re.fullmatch(r"[A-Za-z0-9]{6}", row[8]) for row in rows))
    alpha_acts = Counter(row[8] for row in rows if re.search(r"[A-Za-z]", row[8]))
    add_check(
        checks,
        "alphanumeric_act_code_review",
        sum(alpha_acts.values()),
        "; ".join(f"{code}:{count}" for code, count in sorted(alpha_acts.items())),
        review=True,
    )
    add_check(checks, "ssid_10_digits", sum(not re.fullmatch(r"[0-9]{10}", row[11]) for row in rows))
    ssids = [row[11] for row in rows]
    add_check(checks, "duplicate_ssid_across_request_files", len(ssids) - len(set(ssids)))
    add_check(checks, "gender_domain", sum(row[12] not in {"", "M", "F"} for row in rows))
    add_check(checks, "ethnicity_domain", sum(row[13] not in RACE_CODES for row in rows))
    add_check(checks, "yes_no_indicator_domains", sum(row[index] not in YES_NO_CODES for row in rows for index in (14, 19, 22)))
    add_check(checks, "reserved_fields_blank", sum(row[index] != "" for row in rows for index in (1, 9, 10, 15, 16, 17, 18, 20, 21)))
    add_check(checks, "program_code_domain", sum(not PROGRAM_RE.fullmatch(row[23]) for row in rows))
    add_check(checks, "education_level_ED", sum(row[24] != "ED" for row in rows))
    add_check(checks, "leading_or_trailing_whitespace", sum(value != value.strip() for row in rows for value in row))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "status", "count", "details"])
        writer.writeheader()
        writer.writerows(checks)

    failed = sum(item["status"] == "FAIL" for item in checks)
    review = sum(item["status"] == "REVIEW" for item in checks)
    print(
        f"AVID domain audit: files={len(manifest)} rows={len(rows)} "
        f"checks={len(checks)} failed={failed} review={review} output={output_path}"
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
