# Build the migrant summary workbook from parsed tables; review title and scope for the intended audience. REQ-15, DEC-23.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter


ROOT = Path("migrant_workflow/parsed")
OUTPUT_DIR = Path("migrant_workflow/output")
MIN_CLASS_YEAR = 2018


def workbook_title(district_summary: pd.DataFrame, override: str | None = None) -> str:
    """Label the participating scope, without assuming every county district is present."""
    if override is not None:
        if not override.strip():
            raise ValueError("Workbook title must not be blank")
        return override.strip()
    districts = sorted(set(district_summary["district"].dropna().astype(str).str.strip()) - {""})
    if not districts:
        raise ValueError("Cannot determine workbook scope from empty district metrics")
    scope = districts[0] if len(districts) == 1 else "Participating Districts"
    return f"{scope} - Migrant StudentTracker Summary"


SUMMARY_TITLES = {
    "Immediate Enrollment": "Count of Students Enrolled in College the Fall Immediately Following Graduation From High School",
    "First Year Enrollment": "Count of Students Enrolled in College at Any Time During the First Year After High School",
    "First Two Years Enrollment": "Count of Students Enrolled in College at Any Time During the First Two Years After High School",
    "High School Graduates with a College Degree": "Count of High School Graduates with a College Degree",
    "Time to College Graduation": "Time to College Graduation Within Six Years (Associate's, Bachelor's and Higher)",
}

SUMMARY_GROUPS = {
    "Immediate Enrollment": [
        "Total in the Class",
        "Total Enrolled",
        "Total in Public",
        "Total in Private",
        "Total in 4-Year",
        "Total in 2-Year",
        "Total In-State",
        "Total Out-Of-State",
    ],
    "First Year Enrollment": [
        "Total in the Class",
        "Total Enrolled",
        "Total in Public",
        "Total in Private",
        "Total in 4-Year",
        "Total in 2-Year",
        "Total In-State",
        "Total Out-Of-State",
    ],
    "First Two Years Enrollment": [
        "Total in the Class",
        "Total Enrolled",
        "Total in Public",
        "Total in Private",
        "Total in 4-Year",
        "Total in 2-Year",
        "Total In-State",
        "Total Out-of-State",
    ],
    "High School Graduates with a College Degree": [
        "Total in the Class",
        "Total With a Degree",
        "Total from Public",
        "Total from Private",
        "Total from 4-Year",
        "Total from 2-Year",
        "Total In-State",
        "Total Out-Of-State",
    ],
    "Time to College Graduation": [
        "Total In the Class",
        "Graduated in 2 Years or Less",
        "Graduated in 3 Years",
        "Graduated in 4 Years",
        "Graduated in 5 Years",
        "Graduated in 6 Years",
    ],
}

GROUP_ALIASES = {
    "Total In the Class": ["Total In the Class", "Total in the Class"],
    "Total in the Class": ["Total in the Class", "Total In the Class"],
    "Total Out-of-State": ["Total Out-of-State", "Total Out-Of-State"],
    "Total Out-Of-State": ["Total Out-Of-State", "Total Out-of-State"],
}

PERSISTENCE_DISPLAY = [
    ("All Institutions", "Enrolled Anywhere 1st Year", "Enrolled Anywhere 2nd Year"),
    ("Public Institutions", "In Public 1st Year", "Enrolled Anywhere 2nd Year"),
    ("Private Institutions", "In Private 1st Year", "Enrolled Anywhere 2nd Year"),
    ("4-Year Institutions", "In 4-Year 1st Year", "Enrolled Anywhere 2nd Year"),
    ("2-Year Institutions", "In 2-Year 1st Year", "Enrolled Anywhere 2nd Year"),
    ("In-State Institutions", "In-State 1st Year", "Enrolled Anywhere 2nd Year"),
    ("Out-of-State Institutions", "Out-of-State 1st Year", "Enrolled Anywhere 2nd Year"),
]

PROGRESS_GROUPS = [
    "New to College",
    "Persisted",
    "Returned After Stop Out",
    "No Longer Enrolled & Not Graduated",
    "Graduated",
    "Not in NSC to Date",
]


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / name, dtype=str)


def as_int(value: str | float | int | None) -> int:
    if value is None or value == "" or pd.isna(value):
        return 0
    return int(float(value))


def as_years(values: Iterable[str]) -> list[str]:
    years = sorted({int(float(v)) for v in values if pd.notna(v) and str(v) != ""})
    return [str(y) for y in years]


def parse_effective_date(district_summary: pd.DataFrame) -> str:
    series = district_summary["effective_date"].dropna()
    if series.empty:
        return ""
    return series.value_counts().index[0]


def parse_effective_year(effective_date: str) -> int | None:
    if not effective_date:
        return None
    try:
        return int(str(effective_date).rsplit(" ", 1)[-1])
    except ValueError:
        return None


def mature_years(years: Iterable[str], effective_year: int | None, *, offset: int | None = None) -> list[str]:
    parsed = [int(y) for y in as_years(years)]
    if offset is not None and effective_year is not None:
        parsed = [year for year in parsed if year <= effective_year - offset]
    parsed = [year for year in parsed if year >= MIN_CLASS_YEAR]
    return [str(year) for year in parsed]


def summary_lookup(df: pd.DataFrame) -> dict[tuple[str, str, str], int]:
    cleaned = df.dropna(subset=["category", "Group", "class_year"])
    return {
        (row["category"], row["Group"], row["class_year"]): as_int(row["n"])
        for _, row in cleaned.iterrows()
    }


def get_summary_value(lookup: dict[tuple[str, str, str], int], category: str, group: str, year: str) -> int | None:
    group_candidates = GROUP_ALIASES.get(group, [group])
    for candidate in group_candidates:
        value = lookup.get((category, candidate, year))
        if value is not None:
            return value
    return None


def build_persistence_counts(district_summary: pd.DataFrame) -> tuple[dict[tuple[str, str, str], int], dict[str, int], list[str]]:
    returned = district_summary[district_summary["category"] == "Returned for second year"].copy()
    returned = returned.dropna(subset=["class_year"])
    effective_year = parse_effective_year(parse_effective_date(district_summary))

    class_size_rows = returned[returned["persistence_stage"] == "class_size"].copy()
    class_sizes = (
        class_size_rows.groupby("class_year", as_index=False)["n"]
        .apply(lambda x: sum(as_int(v) for v in x))
    )
    class_size_lookup = dict(zip(class_sizes["class_year"], class_sizes["n"]))

    detail = returned[returned["persistence_stage"].isin(["first_year", "second_year"])].copy()
    grouped = (
        detail.groupby(["class_year", "persistence_group", "persistence_stage"], as_index=False)["n"]
        .apply(lambda x: sum(as_int(v) for v in x))
    )
    lookup = {
        (row["class_year"], row["persistence_group"], row["persistence_stage"]): row["n"]
        for _, row in grouped.iterrows()
    }
    years = mature_years(class_size_lookup.keys(), effective_year, offset=3)
    return lookup, class_size_lookup, years


def build_progress_tables(district_progress: pd.DataFrame) -> tuple[dict[tuple[str, str, str], int], dict[str, int], dict[str, list[str]]]:
    progress = district_progress.dropna(subset=["class_year", "academic_year", "Group"]).copy()
    progress = progress[progress["class_year"].astype(str).astype(int) >= MIN_CLASS_YEAR].copy()
    progress["n_int"] = progress["n"].map(as_int)
    progress["total_int"] = progress["total_in_class"].map(as_int)

    total_lookup = (
        progress[["district", "class_year", "total_int"]]
        .drop_duplicates()
        .groupby("class_year", as_index=False)["total_int"]
        .sum()
    )
    totals = dict(zip(total_lookup["class_year"], total_lookup["total_int"]))

    grouped = progress.groupby(["class_year", "academic_year", "Group"], as_index=False)["n_int"].sum()
    lookup = {
        (row["class_year"], row["academic_year"], row["Group"]): int(row["n_int"])
        for _, row in grouped.iterrows()
    }

    year_to_academic = {}
    for class_year, part in grouped.groupby("class_year"):
        academic_years = sorted(
            part["academic_year"].dropna().unique(),
            key=lambda x: int(str(x).split("-")[0]),
        )
        year_to_academic[class_year] = academic_years

    return lookup, totals, year_to_academic


def format_sheet(ws) -> None:
    ws.column_dimensions["A"].width = 62
    for col in range(2, 12):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.freeze_panes = "B5"


def write_row(ws, row: int, values: list, *, bold: bool = False) -> None:
    font = Font(bold=bold)
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = font
        cell.alignment = Alignment(vertical="top")


def write_summary_section(ws, start_row: int, title: str, effective_date: str, years: list[str], groups: list[str], lookup: dict) -> int:
    write_row(ws, start_row, [title], bold=True)
    if effective_date:
        write_row(ws, start_row + 1, [f"Effective Date = {effective_date}"])
    header_row = start_row + 3
    write_row(ws, header_row, ["Class of", *[int(y) for y in years]], bold=True)
    for offset, group in enumerate(groups, start=1):
        row = header_row + offset
        values = [get_summary_value(lookup, title_map_inverse[title], group, year) for year in years]
        write_row(ws, row, [group, *values])
    return header_row + len(groups) + 1


def write_persistence_section(ws, start_row: int, effective_date: str, years: list[str], detail_lookup: dict, class_sizes: dict) -> int:
    write_row(ws, start_row, ["Count of Students Enrolled in College the First Year After High School Who Returned for a"], bold=True)
    write_row(ws, start_row + 1, ["Second Year (Freshman to Sophomore Retention)"], bold=True)
    if effective_date:
        write_row(ws, start_row + 2, [f"Effective Date = {effective_date}"])
    header_row = start_row + 4
    write_row(ws, header_row, ["Class of", *[int(y) for y in years]], bold=True)
    write_row(ws, header_row + 1, ["Total in the Class", *[class_sizes.get(y) for y in years]])

    row = header_row + 3
    for persistence_group, first_label, second_label in PERSISTENCE_DISPLAY:
        first_values = [detail_lookup.get((y, persistence_group, "first_year")) for y in years]
        second_values = [detail_lookup.get((y, persistence_group, "second_year")) for y in years]
        write_row(ws, row, [first_label, *first_values])
        write_row(ws, row + 1, [second_label, *second_values])
        row += 3
    return row


def write_progress_section(ws, start_row: int, class_year: str, academic_years: list[str], total_in_class: int, lookup: dict) -> int:
    write_row(ws, start_row, [f"Count of Class {class_year}  Postsecondary Enrollment and Progress"], bold=True)
    write_row(ws, start_row + 1, ["Total in the Class:", total_in_class])
    write_row(ws, start_row + 2, ["Academic Years", *academic_years], bold=True)
    row = start_row + 3
    for group in PROGRESS_GROUPS:
        values = [lookup.get((class_year, academic_year, group), 0) for academic_year in academic_years]
        write_row(ws, row, [group, *values])
        row += 1
    return row


def write_mci_section(ws, start_row: int, county_mci: pd.DataFrame) -> int:
    write_row(
        ws,
        start_row,
        ["Most Common Institutions of Enrollment in the Fall Immediately following High School Graduation"],
        bold=True,
    )
    write_row(ws, start_row + 1, [" for All Classes by Number of Students"], bold=True)
    header_row = start_row + 3
    columns = ["Name", "Rank", "State", "Level", "Type", "Total"]
    write_row(ws, header_row, columns, bold=True)
    row = header_row + 1
    for _, record in county_mci.iterrows():
        write_row(
            ws,
            row,
            [
                record["Name"],
                as_int(record["Rank"]),
                record["State"],
                record["Level"],
                record["Type"],
                as_int(record["Total"]),
            ],
        )
        row += 1
    return row


def write_mci_final_sheet(ws, county_mci: pd.DataFrame) -> None:
    columns = ["Name", "Rank", "State", "Level", "Type", "Total"]
    write_row(ws, 1, columns, bold=True)
    row = 2
    for _, record in county_mci.iterrows():
        write_row(
            ws,
            row,
            [
                record["Name"],
                as_int(record["Rank"]),
                record["State"],
                record["Level"],
                record["Type"],
                as_int(record["Total"]),
            ],
        )
        row += 1


title_map_inverse = {v: k for k, v in SUMMARY_TITLES.items()}


def build_workbook(title: str | None = None) -> Path:
    district_summary = read_csv("all_sheet_district_metrics.csv")
    district_progress = read_csv("all_sheet_progress_district_metrics.csv")
    county_summary = read_csv("all_sheet_county_metrics.csv")
    county_mci = read_csv("mci_county_candidates.csv")

    effective_date = parse_effective_date(district_summary)
    effective_year = parse_effective_year(effective_date)
    summary_year_offsets = {
        "High School Graduates with a College Degree": 7,
        "Time to College Graduation": 7,
    }
    summary_years = {
        category: mature_years(
            county_summary.loc[
                (county_summary["category"] == category)
                & (county_summary["Group"].isin(["Total in the Class", "Total In the Class"])),
                "class_year",
            ],
            effective_year,
            offset=summary_year_offsets.get(category),
        )
        for category in [
            "Immediate Enrollment",
            "First Year Enrollment",
            "First Two Years Enrollment",
            "High School Graduates with a College Degree",
            "Time to College Graduation",
        ]
    }

    summary_values = summary_lookup(county_summary)
    persistence_lookup, class_size_lookup, persistence_years = build_persistence_counts(district_summary)
    progress_lookup, progress_totals, progress_year_map = build_progress_tables(district_progress)

    year_token = "2026"
    if effective_date:
        year_token = effective_date.rsplit(" ", 1)[-1]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"_All{year_token}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "All"
    mci_ws = wb.create_sheet("MCI Final")

    format_sheet(ws)
    format_sheet(mci_ws)
    mci_ws.freeze_panes = "A2"

    write_row(ws, 1, [workbook_title(district_summary, title)], bold=True)

    row = 2
    for category in ["Immediate Enrollment", "First Year Enrollment", "First Two Years Enrollment"]:
        row = write_summary_section(
            ws=ws,
            start_row=row,
            title=SUMMARY_TITLES[category],
            effective_date=effective_date,
            years=summary_years[category],
            groups=SUMMARY_GROUPS[category],
            lookup=summary_values,
        )

    row = write_persistence_section(
        ws=ws,
        start_row=row,
        effective_date=effective_date,
        years=persistence_years,
        detail_lookup=persistence_lookup,
        class_sizes=class_size_lookup,
    )

    for category in ["High School Graduates with a College Degree", "Time to College Graduation"]:
        row = write_summary_section(
            ws=ws,
            start_row=row,
            title=SUMMARY_TITLES[category],
            effective_date=effective_date if category == "High School Graduates with a College Degree" else "",
            years=summary_years[category],
            groups=SUMMARY_GROUPS[category],
            lookup=summary_values,
        )

    progress_years = sorted(progress_year_map.keys(), key=int)
    for class_year in progress_years:
        if progress_totals.get(class_year, 0) <= 0:
            continue
        row = write_progress_section(
            ws=ws,
            start_row=row,
            class_year=class_year,
            academic_years=progress_year_map[class_year],
            total_in_class=progress_totals[class_year],
            lookup=progress_lookup,
        )

    write_mci_section(ws, row, county_mci)
    write_mci_final_sheet(mci_ws, county_mci)

    wb.save(out_path)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a migrant summary for the participating districts")
    parser.add_argument("--title", help="Explicit workbook scope label; otherwise derive from district metrics")
    output_path = build_workbook(title=parser.parse_args().title)
    print(f"Wrote {output_path}")
