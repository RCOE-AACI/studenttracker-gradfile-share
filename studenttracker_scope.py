# Shared class-span validation: custom requests require declared classes; annual graduate submissions require exactly one. REQ-29.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
"""Shared class-span guards for StudentTracker outbound batches."""

from __future__ import annotations

import re
from collections.abc import Iterable


def parse_year_expression(value: str, *, option_name: str = "--cohort-years") -> tuple[int, ...]:
    """Parse an ascending consecutive YYYY-YYYY range or comma-separated years."""
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{4}", text):
        start, end = (int(part) for part in text.split("-", maxsplit=1))
        if start > end:
            raise ValueError(f"{option_name} range must be ascending")
        years = tuple(range(start, end + 1))
    else:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        try:
            parsed = tuple(int(part) for part in parts)
        except ValueError as exc:
            raise ValueError(
                f"{option_name} must be YYYY-YYYY or comma-separated years"
            ) from exc
        if len(set(parsed)) != len(parsed):
            raise ValueError(f"{option_name} must not repeat a year")
        years = tuple(sorted(parsed))
    if not years:
        raise ValueError(f"{option_name} must include at least one year")
    if years != tuple(range(min(years), max(years) + 1)):
        raise ValueError(f"{option_name} must be consecutive")
    return years


def validate_request_cohort_years(
    years: Iterable[int], *, minimum: int = 1, context: str = "request batch"
) -> tuple[int, ...]:
    """Validate declared request classes; a single class is allowed."""
    normalized = tuple(sorted(set(int(year) for year in years)))
    if len(normalized) < minimum:
        raise ValueError(
            f"{context} must include at least {minimum} distinct graduating classes; "
            f"received {len(normalized)}"
        )
    return normalized


def validate_graduate_cohort_years(
    years: Iterable[int], *, context: str = "graduate submission batch"
) -> tuple[int, ...]:
    """Require a standard graduate submission to contain exactly one class."""
    normalized = tuple(sorted(set(int(year) for year in years)))
    if len(normalized) != 1:
        raise ValueError(
            f"{context} must include exactly one graduating class; "
            f"received {len(normalized)}"
        )
    return normalized
