# TVUSD request: normalize school labels, intersect source identifiers, audit blockers, and serialize a source-bounded request. REQ-07.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd


SOURCE_PATH = Path("data/TVUSDClass2025.csv")
ACCOUNT_REFS_PATH = Path("data/account_refs.xlsx")
REQUEST_DIR = Path("requestfiles")
TEST_REQUEST_DIR = REQUEST_DIR / "test_file"
AUDIT_DIR = Path("audit")

BATCH_SUFFIX = "TVUSD"
TVUSD_SA = "90000001"
TVUSD_DISTRICT = "TEMECULA VALLEY UNIFIED SCHOOL DISTRICT"


def normalize_token(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", "" if pd.isna(value) else str(value).upper())


def normalize_school(value: object) -> str:
    token = normalize_token(re.sub(r"^[^-]+ - ", "", "" if pd.isna(value) else str(value)))
    token = re.sub(r"SENIOR", "", token)
    token = re.sub(r"SCHOOL", "", token)
    token = re.sub(r"HIGH$", "HIGHSCHOOL", token)
    return token


def format_yyyymmdd(value: object) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y%m%d")


def missing(value: object) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def coalesce_text(left: pd.Series, right: pd.Series) -> pd.Series:
    cleaned = left.mask(left.isna() | left.astype(str).str.strip().eq(""))
    return cleaned.combine_first(right)


def yn(value: object) -> str:
    if value == "Yes":
        return "Y"
    if value == "No":
        return "N"
    return ""


def race_code(value: object) -> str:
    return {
        "African American": "BL",
        "Asian": "AS",
        "Filipino": "AS",
        "Native American": "AM",
        "Pacific Islander": "PI",
        "Two or More": "MU",
        "White": "WH",
        "Hispanic": "HI",
    }.get(value, "")


def load_latest_cohort() -> pd.DataFrame:
    cohort_paths = sorted(Path("data").glob("*_152_account.parquet"))
    frames = []
    keep_cols = [
        "SSID",
        "DistrictCode",
        "SchoolCode",
        "StudentEnrollmentExitDate",
        "Gender",
        "EthnicityRace",
        "SocioEconomicallyDisadvantaged",
        "EnglishLearner",
        "StudentswithDisabilities",
        "FosterYouth",
        "Homeless",
        "Sealofbiliteracy",
        "UC_CSURequirementsMet",
        "CohortYear",
    ]
    for path in cohort_paths:
        curr = pd.read_parquet(path)
        curr = curr[[c for c in keep_cols if c in curr.columns]].copy()
        curr["cohort_source"] = path.name
        frames.append(curr)

    cohort = pd.concat(frames, ignore_index=True)
    cohort["SSID"] = cohort["SSID"].astype(str).str.strip()
    cohort["DistrictCode"] = cohort["DistrictCode"].astype(str).str.strip()
    cohort["SchoolCode"] = cohort["SchoolCode"].astype(str).str.strip()
    cohort["CDS"] = cohort["DistrictCode"] + cohort["SchoolCode"]
    cohort["StudentEnrollmentExitDate_parsed"] = pd.to_datetime(
        cohort["StudentEnrollmentExitDate"], errors="coerce"
    )
    cohort["CohortYear_sort"] = pd.to_numeric(cohort.get("CohortYear"), errors="coerce")
    return (
        cohort.sort_values(
            ["SSID", "StudentEnrollmentExitDate_parsed", "CohortYear_sort"],
            ascending=[True, False, False],
        )
        .drop_duplicates("SSID", keep="first")
        .drop(columns=["StudentEnrollmentExitDate_parsed", "CohortYear_sort"])
    )


def main() -> None:
    run_date = date.today().strftime("%Y%m%d")
    REQUEST_DIR.mkdir(exist_ok=True)
    TEST_REQUEST_DIR.mkdir(exist_ok=True)
    AUDIT_DIR.mkdir(exist_ok=True)

    source = pd.read_csv(SOURCE_PATH, dtype=str).fillna("")
    source = source.assign(
        source_row=lambda df: range(2, len(df) + 2),
        SSID=lambda df: df["SSID"].astype(str).str.strip(),
        SEIS_ID=lambda df: df["SEIS ID"].astype(str).str.strip(),
        district_norm=lambda df: df["District of Service (Reporting LEA)"].map(normalize_token),
        school_norm=lambda df: df["School of Attendance"].map(normalize_school),
        BirthDate_parsed=lambda df: pd.to_datetime(df["Date of Birth"], errors="coerce"),
        ExitDate_parsed=lambda df: pd.to_datetime(df["Date of Exit from SpEd"], errors="coerce"),
    )

    cohort = load_latest_cohort()
    refs = pd.read_excel(ACCOUNT_REFS_PATH, dtype=str).fillna("")
    refs = refs.assign(
        CDS=lambda df: df["CDS"].astype(str).str.strip(),
        district_norm=lambda df: df["District"].map(normalize_token),
        school_norm=lambda df: df["HSName"].map(normalize_school),
    )
    tvusd_refs = refs.loc[refs["SA"].astype(str).str.strip() == TVUSD_SA].copy()

    by_cds = tvusd_refs[["CDS", "District", "SA", "ACT", "HSName"]].drop_duplicates("CDS")
    by_school = tvusd_refs[
        ["school_norm", "District", "SA", "ACT", "HSName"]
    ].drop_duplicates("school_norm")

    enriched = (
        source.merge(cohort, how="left", on="SSID", suffixes=("", "_cohort"))
        .merge(by_cds, how="left", on="CDS", suffixes=("", "_by_cds"))
        .rename(
            columns={
                "District": "District_cds",
                "SA": "SA_cds",
                "ACT": "ACT_cds",
                "HSName": "HSName_cds",
            }
        )
        .merge(by_school, how="left", on="school_norm", suffixes=("", "_by_school"))
        .rename(
            columns={
                "District": "District_school",
                "SA": "SA_school",
                "ACT": "ACT_school",
                "HSName": "HSName_school",
            }
        )
    )
    enriched["District"] = coalesce_text(enriched["District_cds"], enriched["District_school"])
    enriched["SA"] = coalesce_text(enriched["SA_cds"], enriched["SA_school"])
    enriched["ACT"] = coalesce_text(enriched["ACT_cds"], enriched["ACT_school"])
    enriched["HSName"] = coalesce_text(enriched["HSName_cds"], enriched["HSName_school"])
    enriched["LastAttendanceDate"] = coalesce_text(
        enriched["StudentEnrollmentExitDate"], enriched["Date of Exit from SpEd"]
    )

    def blocker_reason(row: pd.Series) -> str:
        reasons = []
        if missing(row["First Name"]):
            reasons.append("Missing first name")
        if missing(row["Last Name"]):
            reasons.append("Missing last name")
        if pd.isna(row["BirthDate_parsed"]):
            reasons.append("Missing date of birth")
        if not format_yyyymmdd(row["LastAttendanceDate"]):
            reasons.append("Missing last date of attendance")
        if missing(row.get("SA", "")):
            reasons.append("Missing account code")
        if missing(row.get("ACT", "")):
            reasons.append("Missing ACT code")
        return "; ".join(reasons)

    enriched["blocker_reason"] = enriched.apply(blocker_reason, axis=1)
    blockers = enriched.loc[enriched["blocker_reason"].astype(str).str.len() > 0].copy()
    blocker_path = AUDIT_DIR / f"{run_date}_tvusd_request_blockers.csv"
    blockers[
        [
            "source_row",
            "SSID",
            "SEIS_ID",
            "District of Service (Reporting LEA)",
            "School of Attendance",
            "blocker_reason",
        ]
    ].to_csv(blocker_path, index=False)

    ready = enriched.loc[enriched["blocker_reason"].astype(str).str.len() == 0].copy()
    ready = ready.loc[ready["SA"].astype(str).str.strip() == TVUSD_SA].copy()
    ready = ready.sort_values(["HSName", "Last Name", "First Name", "SSID"])

    header = ["H3", TVUSD_SA, "", TVUSD_DISTRICT, run_date, "SE", "D"]
    rows = []
    for row in ready.to_dict("records"):
        rows.append(
            [
                "D3",
                "",
                row["First Name"],
                "",
                row["Last Name"],
                "",
                format_yyyymmdd(row["BirthDate_parsed"]),
                format_yyyymmdd(row["LastAttendanceDate"]),
                row["ACT"],
                "",
                row["SEIS_ID"],
                row["SSID"],
                row["Gender"] if row.get("Gender") in {"M", "F"} else "",
                race_code(row.get("EthnicityRace")),
                yn(row.get("SocioEconomicallyDisadvantaged")),
                "",
                "",
                "",
                "",
                yn(row.get("EnglishLearner")),
                "",
                "",
                yn(row.get("StudentswithDisabilities")),
                ".".join(
                    [
                        "TVUSD",
                        f"GRADE_{row['Grade Code']}",
                        f"EXIT_{row['Exit Reason']}",
                    ]
                ),
                "ED",
            ]
        )

    trailer = ["T3", str(len(rows) + 2)]
    output_path = REQUEST_DIR / f"{run_date}_{TVUSD_SA}_TEMECULAVALLEYUNIFIEDSCHOOLDISTRICT_{BATCH_SUFFIX}.txt"
    test_path = TEST_REQUEST_DIR / f"{TVUSD_SA}_TEMECULAVALLEYUNIFIEDSCHOOLDISTRICT_{BATCH_SUFFIX}.txt"

    for path, body_rows in [(output_path, rows), (test_path, rows[:800])]:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("\t".join(header) + "\n")
            for record in body_rows:
                f.write("\t".join("" if pd.isna(v) else str(v) for v in record) + "\n")
            f.write("\t".join(["T3", str(len(body_rows) + 2)]) + "\n")

    summary = (
        ready.groupby(["SA", "ACT", "District", "HSName"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values(["District", "HSName", "ACT"])
    )
    summary_path = AUDIT_DIR / f"{run_date}_tvusd_request_summary.csv"
    summary.to_csv(summary_path, index=False)

    print(f"source_rows={len(source)}")
    print(f"ready_rows={len(rows)}")
    print(f"blocked_rows={len(blockers)}")
    print(f"request_file={output_path}")
    print(f"test_file={test_path}")
    print(f"summary_file={summary_path}")
    print(f"blocker_file={blocker_path}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
