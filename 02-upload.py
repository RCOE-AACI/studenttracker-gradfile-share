# Transfer/report helpers: select exact intended batches, retain date-scoped transfer state, and keep student-level DETAIL files outside report ZIPs. REQ-09 through REQ-13.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
import csv
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path

import pandas as pd
import paramiko
from pypdf import PageObject, PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from studenttracker_scope import (
    validate_graduate_cohort_years,
    validate_request_cohort_years,
)

# Local-only inputs are loaded at import time. The sharing copy has zero credential rows
# and a header-only account workbook, so imports do not expose production accounts.
# Populate these only in an authorized operational copy.
# Credentials
with open("creds.csv", encoding="utf-8-sig", newline="") as creds_file:
    creds = list(csv.DictReader(creds_file))

# Refs is the school-to-account crosswalk, not the credential list. Keep codes as text.
# See docs/accounts_and_report_naming.md for source structure and routing rules.
accts = pd.read_excel("data/account_refs.xlsx", sheet_name="Refs", dtype=str)
districts = accts[["SA", "District"]].drop_duplicates()
districts["District"] = districts["District"].str.removesuffix(" SCHOOL DISTRICT")
schools = accts[["SA", "ACT", "HSName"]]

# Get todays date
date = datetime.date.today().strftime("%Y%m%d")

_VENDOR_REPORT_RE = re.compile(
    r"^(?P<user>[A-Za-z0-9]+)_(?P<sa>\d{8})_(?P<act>[A-Za-z0-9]+)_(?P<job>\d+)_"
)
_DETAIL_FILE_RE = re.compile(
    r"^(?P<user>[A-Za-z0-9]+)_(?P<sa>\d{8})[-_](?P<job>\d+)[-_]DETAIL[-_]EFFDT[-_](?P<effdt>\d{8})[-_]RUNDT[-_](?P<rundt>\d{8,})\.csv$",
    flags=re.IGNORECASE,
)
_ANY_SA_RE = re.compile(r"_(?P<sa>\d{8})(?:[-_]|$)")

DEFAULT_REPORT_BATCH_SPECS = (
    {
        "batch_type": "SPRING_REGULAR",
        "label": "Spring regular report (auto-generated from fall grad file)",
        "glob": "submissionfiles/20260127_*.txt",
    },
    {
        "batch_type": "MIGRANT",
        "label": "Migrant request",
        "glob": "requestfiles/20260422_*.txt",
        "exclude_suffix": "_SELPA.txt",
    },
    {
        "batch_type": "SELPA",
        "label": "SELPA request",
        "glob": "requestfiles/20260422_*_SELPA.txt",
    },
    {
        "batch_type": "CTE",
        "label": "Class-of-2025 CTE completers",
        "glob": "requestfiles/20260828_*_CTE.txt",
    },
)

CTE_REPORT_SUFFIX = "_CTE"
CTE_REPORT_HEADER = (
    "CTE STUDENTTRACKER REPORT - THIS REPORT IS ONLY FOR CTE COMPLETERS"
)


class TransferAuthenticationError(RuntimeError):
    """Stop a multi-account transfer run after the first failed login."""

def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value))


def _normalize_act_token(act_token):
    token = str(act_token).strip().upper()
    if token.startswith("HSA") and token[3:].isdigit():
        return f"A{token[3:]}"
    if token.startswith("HS") and token[2:].isdigit():
        token = token[2:]
    if token.isdigit() and len(token) <= 6:
        token = token.zfill(6)
    return token


def _report_type_from_name(filename):
    name_upper = filename.upper()
    if "ACADEMICS" in name_upper:
        return "_Academics"
    if "BASIC" in name_upper:
        return "_Basic"
    if "DEMOGRAPHICS" in name_upper:
        return "_Demographics"
    if "TOP25" in name_upper:
        return "_Top25"
    return "_Unknown"


def _extract_batch_tag(filename):
    effdt_match = re.search(r"EFFDT[_-](\d{8})", filename, flags=re.IGNORECASE)
    rundt_match = re.search(r"RUNDT[_-](\d{8,})", filename, flags=re.IGNORECASE)
    tags = []
    if effdt_match:
        tags.append(f"EFFDT{effdt_match.group(1)}")
    if rundt_match:
        # Keep RUNDT in outputs as date only (YYYYMMDD), even if source includes time.
        tags.append(f"RUNDT{rundt_match.group(1)[:8]}")
    if tags:
        return f"_{'_'.join(tags)}"
    return ""


def _next_available_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    idx = 2
    while True:
        candidate = f"{stem}__dup{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def _renamed_zip_name(district, suffix=""):
    return f"{district}{suffix}_renamed.zip"


def _move_or_dedupe(src_path, dest_path):
    if os.path.exists(dest_path):
        if _files_identical(src_path, dest_path):
            os.remove(src_path)
            return
        dest_path = _next_available_path(dest_path)
    shutil.move(src_path, dest_path)


def _files_identical(first, second):
    """Equal byte counts alone do not establish that two returned reports are duplicates."""
    if os.path.getsize(first) != os.path.getsize(second):
        return False
    def digest(path):
        with open(path, "rb") as stream:
            return hashlib.file_digest(stream, "sha256").digest()
    return digest(first) == digest(second)


def _is_detail_filename(filename):
    upper_name = filename.upper()
    return (
        filename.lower().endswith(".csv")
        and ("-DETAIL-" in upper_name or "_DETAIL_" in upper_name)
    )


def _extract_rundt_date(filename):
    match = re.search(r"RUNDT[_-](\d{8,})", filename, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)[:8]


def _extract_effdt_date(filename):
    match = re.search(r"EFFDT[_-](\d{8})", filename, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _normalize_rundt_filters(filter_rundt):
    if filter_rundt in ("", None):
        return None
    if isinstance(filter_rundt, (list, tuple, set)):
        values = filter_rundt
    else:
        values = [filter_rundt]

    filters = set()
    for value in values:
        value_str = str(value).strip()
        if not value_str:
            continue
        filters.add(value_str[:8])
    return filters or None


def _matches_rundt_filter(filename, rundt_filters):
    if not rundt_filters:
        return True
    rundt_date = _extract_rundt_date(filename)
    if rundt_date is None:
        return False
    return rundt_date in rundt_filters


def _normalize_effdt_filters(filter_effdt):
    if filter_effdt in ("", None):
        return None
    if isinstance(filter_effdt, (list, tuple, set)):
        values = filter_effdt
    else:
        values = [filter_effdt]

    filters = set()
    for value in values:
        value_str = str(value).strip()
        if not value_str:
            continue
        # Support month filters (YYYYMM) and exact day filters (YYYYMMDD).
        if len(value_str) >= 8:
            filters.add(value_str[:8])
        elif len(value_str) >= 6:
            filters.add(value_str[:6])
    return filters or None


def _matches_effdt_filter(filename, effdt_filters):
    if not effdt_filters:
        return True
    effdt_date = _extract_effdt_date(filename)
    if effdt_date is None:
        return False
    for f in effdt_filters:
        if len(f) == 6 and effdt_date.startswith(f):
            return True
        if len(f) == 8 and effdt_date == f:
            return True
    return False


def _extract_detail_job(filename):
    match = _DETAIL_FILE_RE.match(filename)
    if not match:
        return None
    return match.group("job")


def _extract_zip_job(path):
    try:
        with zipfile.ZipFile(path) as zipfile_ref:
            jobs = []
            for name in zipfile_ref.namelist():
                parsed = _VENDOR_REPORT_RE.match(Path(name).name)
                if parsed:
                    jobs.append(parsed.group("job"))
    except zipfile.BadZipFile:
        return None
    if not jobs:
        return None
    job_counts = {}
    for job in jobs:
        job_counts[job] = job_counts.get(job, 0) + 1
    return max(job_counts.items(), key=lambda item: item[1])[0]


def _select_comprehensive_download_names(src_folder, rundt_filters, effdt_filters):
    detail_candidates = []
    for name in os.listdir(src_folder):
        path = os.path.join(src_folder, name)
        if not os.path.isfile(path):
            continue
        if not _is_detail_filename(name):
            continue
        if not _matches_rundt_filter(name, rundt_filters):
            continue
        if not _matches_effdt_filter(name, effdt_filters):
            continue

        rundt_date = _extract_rundt_date(name)
        job_token = _extract_detail_job(name)
        if rundt_date is None or job_token is None:
            continue
        detail_candidates.append(
            {
                "name": name,
                "job": job_token,
                "rundt": rundt_date,
                "size": os.path.getsize(path),
            }
        )

    if not detail_candidates:
        return None

    latest_rundt = max(candidate["rundt"] for candidate in detail_candidates)
    latest_candidates = [
        candidate
        for candidate in detail_candidates
        if candidate["rundt"] == latest_rundt
    ]
    selected_detail = max(
        latest_candidates,
        key=lambda candidate: (candidate["size"], candidate["job"]),
    )
    selected_names = {selected_detail["name"]}

    for name in os.listdir(src_folder):
        path = os.path.join(src_folder, name)
        if not os.path.isfile(path):
            continue
        if not name.lower().endswith(".zip"):
            continue
        if not _matches_rundt_filter(name, rundt_filters):
            continue
        if not _matches_effdt_filter(name, effdt_filters):
            continue
        if _extract_rundt_date(name) != latest_rundt:
            continue
        if _extract_zip_job(path) == selected_detail["job"]:
            selected_names.add(name)

    return selected_names


def _build_school_lookup():
    lookup = {}
    subset = schools.dropna(subset=["SA", "ACT", "HSName"])
    for row in subset.itertuples(index=False):
        sa = str(row.SA).strip().zfill(8)
        act = _normalize_act_token(row.ACT)
        if act.isdigit():
            act = act.zfill(6)
        name = str(row.HSName).strip()
        if not sa.strip("0") or not act or not name:
            continue
        key = (sa, act)
        if key in lookup and lookup[key] != name:
            raise ValueError("Conflicting school names for an SA/ACT mapping in Refs")
        lookup[key] = name
    return lookup


def _state_dir(base, run_date, kind):
    state_dir = os.path.join(base, run_date, kind)
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def _load_state(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def _save_state(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _should_skip_terminal_state(state, force=False):
    return state.get("status") in {"success", "empty", "failed"} and not force


def _matching_upload_files(directory, sa_token, filename_prefixes=None):
    prefixes = None
    if filename_prefixes not in (None, "", []):
        if isinstance(filename_prefixes, (list, tuple, set)):
            prefixes = [str(p) for p in filename_prefixes]
        else:
            prefixes = [str(filename_prefixes)]
    return sorted(
        f
        for f in os.listdir(directory)
        if f.endswith(".txt") and sa_token in f
        and (
            prefixes is None
            or any(f.startswith(prefix) for prefix in prefixes)
        )
    )


def _normalize_name_token(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _normalize_date_token(value):
    digits = re.sub(r"[^0-9]+", "", str(value or ""))
    return digits[:8]


def _student_keys_from_sent_row(row):
    row_type = row[0] if row else ""
    if row_type == "PD3":
        first = _normalize_name_token(row[2] if len(row) > 2 else "")
        middle = _normalize_name_token(row[3] if len(row) > 3 else "")
        last = _normalize_name_token(row[4] if len(row) > 4 else "")
        suffix = _normalize_name_token(row[5] if len(row) > 5 else "")
        act = _normalize_name_token(row[14] if len(row) > 14 else "")
        grad_date = _normalize_date_token(row[11] if len(row) > 11 else "")
    else:
        first = _normalize_name_token(row[2] if len(row) > 2 else "")
        middle = _normalize_name_token(row[3] if len(row) > 3 else "")
        last = _normalize_name_token(row[4] if len(row) > 4 else "")
        suffix = _normalize_name_token(row[5] if len(row) > 5 else "")
        act = _normalize_name_token(row[8] if len(row) > 8 else "")
        grad_date = _normalize_date_token(row[7] if len(row) > 7 else "")
    full_key = (first, middle, last, suffix, act, grad_date)
    relaxed_key = (first, last, act, grad_date)
    return full_key, relaxed_key


def _student_keys_from_detail_row(row):
    first = _normalize_name_token(row.get("First_Name"))
    middle = _normalize_name_token(row.get("Middle_Name"))
    last = _normalize_name_token(row.get("Last_Name"))
    suffix = _normalize_name_token(row.get("Name_Suffix"))
    act = _normalize_name_token(row.get("High_School_Code"))
    grad_date = _normalize_date_token(row.get("High_School_Grad_Date"))
    full_key = (first, middle, last, suffix, act, grad_date)
    relaxed_key = (first, last, act, grad_date)
    return full_key, relaxed_key


def _safe_f1(intersection_size, left_size, right_size):
    if left_size == 0 or right_size == 0 or intersection_size == 0:
        return 0.0, 0.0, 0.0
    precision = intersection_size / left_size
    recall = intersection_size / right_size
    denom = precision + recall
    f1 = 0.0 if denom == 0 else 2 * precision * recall / denom
    return precision, recall, f1


def _load_sent_batch_manifest(batch_specs=None):
    specs = batch_specs or DEFAULT_REPORT_BATCH_SPECS
    manifest = []
    for spec in specs:
        exclude_suffix = spec.get("exclude_suffix")
        for path in sorted(Path(".").glob(spec["glob"])):
            if exclude_suffix and path.name.endswith(exclude_suffix):
                continue

            full_keys = set()
            relaxed_keys = set()
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter="\t")
                for row in reader:
                    if not row or row[0] not in {"D3", "PD3"}:
                        continue
                    full_key, relaxed_key = _student_keys_from_sent_row(row)
                    if any(full_key):
                        full_keys.add(full_key)
                    if any(relaxed_key):
                        relaxed_keys.add(relaxed_key)

            sa = path.name.split("_")[1] if "_" in path.name else ""
            manifest.append(
                {
                    "batch_type": spec["batch_type"],
                    "batch_label": spec.get("label", spec["batch_type"]),
                    "sa": sa,
                    "source_file": str(path),
                    "student_count": len(full_keys),
                    "full_keys": full_keys,
                    "relaxed_keys": relaxed_keys,
                }
            )
    return manifest


def _read_detail_rows(path):
    last_error = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                rows = list(csv.DictReader(f))
            return rows, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def _parse_download_filename(filename):
    parsed = {
        "sa": None,
        "effdt": _extract_effdt_date(filename),
        "rundt": _extract_rundt_date(filename),
    }
    detail_match = _DETAIL_FILE_RE.match(filename)
    if detail_match:
        parsed["sa"] = detail_match.group("sa")
        parsed["job"] = detail_match.group("job")
        return parsed

    vendor_match = _VENDOR_REPORT_RE.match(filename)
    if vendor_match:
        parsed["sa"] = vendor_match.group("sa")
        parsed["job"] = vendor_match.group("job")
        parsed["act"] = vendor_match.group("act")
        parsed["user"] = vendor_match.group("user")
        return parsed

    any_match = _ANY_SA_RE.search(filename)
    if any_match:
        parsed["sa"] = any_match.group("sa")
    return parsed


def _archive_target_dirs(user):
    return ["receive-archive", "/receive-archive", f"/Home/{user}/receive-archive"]


def _receive_target_dirs(user):
    return ["receive", "/receive", f"/Home/{user}/receive"]


def _connect_sftp(cred):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname="ftps.nslc.org",
        port=22,
        username=cred["user"],
        password=cred["pass"],
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    return ssh, ssh.open_sftp()


def _resolve_remote_dir(sftp, target_dirs):
    for directory in target_dirs:
        try:
            sftp.chdir(directory)
            return sftp.getcwd()
        except IOError:
            continue
    return None


def inventory_receive_archive(
    creds,
    output_path=None,
):
    inventory = []
    for cred in creds:
        if cred.get("sa") == "90000003":
            continue

        entry = {
            "district": cred["district"],
            "user": cred["user"],
            "sa": cred["sa"],
            "archive_dir": None,
            "files": [],
            "error": None,
        }
        ssh = None
        sftp = None
        try:
            ssh, sftp = _connect_sftp(cred)
            archive_dir = _resolve_remote_dir(sftp, _archive_target_dirs(cred["user"]))
            entry["archive_dir"] = archive_dir
            if archive_dir:
                entry["files"] = sorted(sftp.listdir("."))
        except Exception as exc:
            entry["error"] = type(exc).__name__
        finally:
            if sftp is not None:
                sftp.close()
            if ssh is not None:
                ssh.close()
        inventory.append(entry)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(inventory, f, indent=2)
    return inventory


def download_receive_archive_missing(
    download_date,
    creds,
    inventory=None,
    output_path=None,
):
    inventory = inventory or inventory_receive_archive(
        creds,
        output_path=output_path,
    )
    downloaded = []
    errors = []
    for entry in inventory:
        if not entry.get("archive_dir") or entry.get("error"):
            continue

        district_dir = Path("downloads") / download_date / entry["district"]
        district_dir.mkdir(parents=True, exist_ok=True)
        existing_names = {path.name for path in district_dir.iterdir() if path.is_file()}
        missing_files = [name for name in entry["files"] if name not in existing_names]
        if not missing_files:
            continue

        cred = next(
            (
                c for c in creds
                if c["district"] == entry["district"] and c["user"] == entry["user"]
            ),
            None,
        )
        if cred is None:
            continue

        ssh = None
        sftp = None
        try:
            ssh, sftp = _connect_sftp(cred)
            archive_dir = _resolve_remote_dir(sftp, [entry["archive_dir"]])
            if not archive_dir:
                continue
            for filename in missing_files:
                local_path = district_dir / filename
                sftp.get(filename, str(local_path))
                downloaded.append(
                    {
                        "district": entry["district"],
                        "user": entry["user"],
                        "filename": filename,
                        "local_path": str(local_path),
                    }
                )
        except Exception as exc:
            errors.append(
                {
                    "district": entry["district"],
                    "user": entry["user"],
                    "error": type(exc).__name__,
                }
            )
        finally:
            if sftp is not None:
                sftp.close()
            if ssh is not None:
                ssh.close()

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "downloaded": downloaded,
                    "errors": errors,
                },
                f,
                indent=2,
            )
    return downloaded


def _score_detail_against_source(detail_keys, source):
    detail_full = detail_keys["full_keys"]
    detail_relaxed = detail_keys["relaxed_keys"]
    source_full = source["full_keys"]
    source_relaxed = source["relaxed_keys"]

    full_intersection = len(detail_full & source_full)
    relaxed_intersection = len(detail_relaxed & source_relaxed)
    full_precision, full_recall, full_f1 = _safe_f1(
        full_intersection, len(detail_full), len(source_full)
    )
    relaxed_precision, relaxed_recall, relaxed_f1 = _safe_f1(
        relaxed_intersection, len(detail_relaxed), len(source_relaxed)
    )

    exact_match = bool(detail_full) and detail_full == source_full
    relaxed_exact = bool(detail_relaxed) and detail_relaxed == source_relaxed
    size_delta = abs(len(detail_full) - len(source_full))

    if exact_match:
        confidence = "high"
    elif full_precision >= 0.98 and full_recall >= 0.98:
        confidence = "high"
    elif relaxed_exact or (relaxed_precision >= 0.98 and relaxed_recall >= 0.98):
        confidence = "medium"
    elif full_f1 >= 0.8 or relaxed_f1 >= 0.8:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "batch_type": source["batch_type"],
        "batch_label": source["batch_label"],
        "source_file": source["source_file"],
        "source_student_count": len(source_full),
        "detail_student_count": len(detail_full),
        "full_overlap": full_intersection,
        "relaxed_overlap": relaxed_intersection,
        "full_precision": round(full_precision, 4),
        "full_recall": round(full_recall, 4),
        "full_f1": round(full_f1, 4),
        "relaxed_precision": round(relaxed_precision, 4),
        "relaxed_recall": round(relaxed_recall, 4),
        "relaxed_f1": round(relaxed_f1, 4),
        "size_delta": size_delta,
        "confidence": confidence,
        "_sort": (
            exact_match,
            full_recall,
            relaxed_recall,
            full_intersection,
            len(source_full),
            full_precision,
            relaxed_intersection,
            -size_delta,
        ),
    }


def _select_scaffold_match(candidate_scores):
    if not candidate_scores:
        return None, "no_source_batch"

    best = candidate_scores[0]
    runner_up = candidate_scores[1] if len(candidate_scores) > 1 else None

    if best["full_recall"] >= 0.995 and best["full_overlap"] >= 5:
        if runner_up is None:
            return best, "auto_full_recall"
        if best["full_recall"] - runner_up["full_recall"] >= 0.02:
            return best, "auto_full_recall"
        if (
            runner_up["full_recall"] >= 0.995
            and best["source_student_count"] > runner_up["source_student_count"]
        ):
            return best, "auto_full_recall_largest"

    if best["full_f1"] >= 0.995:
        return best, "auto_exactish"
    if (
        best["full_f1"] >= 0.95
        and best["full_overlap"] >= 10
        and (runner_up is None or best["full_f1"] - runner_up["full_f1"] >= 0.1)
    ):
        return best, "auto_high"
    if (
        best["relaxed_f1"] >= 0.98
        and best["relaxed_overlap"] >= 10
        and (runner_up is None or best["relaxed_f1"] - runner_up["relaxed_f1"] >= 0.1)
    ):
        return best, "auto_relaxed"
    return None, "review"


def _selection_confidence(selection_reason, best_score):
    if selection_reason in {"auto_exactish", "auto_high"}:
        return "high"
    if selection_reason in {"auto_full_recall", "auto_full_recall_largest", "auto_relaxed"}:
        return "medium"
    if best_score is None:
        return "review"
    return "review"


def scaffold_report_types(download_date, batch_specs=None, output_path=None):
    batch_manifest = _load_sent_batch_manifest(batch_specs=batch_specs)
    candidates_by_sa = {}
    for batch in batch_manifest:
        candidates_by_sa.setdefault(batch["sa"], []).append(batch)

    base_dir = Path("downloads") / download_date
    if not base_dir.exists():
        raise FileNotFoundError(f"No downloads directory found for {download_date}: {base_dir}")

    group_index = {}
    for district_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
        for path in sorted(p for p in district_dir.iterdir() if p.is_file()):
            parsed = _parse_download_filename(path.name)
            group_key = (
                district_dir.name,
                parsed.get("sa"),
                parsed.get("effdt"),
                parsed.get("rundt"),
            )
            group_index.setdefault(group_key, []).append(path.name)

    scaffold_rows = []
    detail_paths = sorted(base_dir.glob("*/*DETAIL*.csv"))
    for detail_path in detail_paths:
        district = detail_path.parent.name
        parsed = _parse_download_filename(detail_path.name)
        detail_sa = parsed.get("sa")
        detail_keys = {"full_keys": set(), "relaxed_keys": set()}
        rows, encoding = _read_detail_rows(detail_path)
        for row in rows:
            full_key, relaxed_key = _student_keys_from_detail_row(row)
            if any(full_key):
                detail_keys["full_keys"].add(full_key)
            if any(relaxed_key):
                detail_keys["relaxed_keys"].add(relaxed_key)

        candidate_scores = [
            _score_detail_against_source(detail_keys, candidate)
            for candidate in candidates_by_sa.get(detail_sa, [])
        ]
        candidate_scores.sort(key=lambda item: item["_sort"], reverse=True)
        selected, selection_reason = _select_scaffold_match(candidate_scores)
        best = selected or (candidate_scores[0] if candidate_scores else None)
        top_candidates = " | ".join(
            (
                f"{item['batch_type']}:full_f1={item['full_f1']},"
                f"relaxed_f1={item['relaxed_f1']},"
                f"overlap={item['full_overlap']}/{item['source_student_count']}"
            )
            for item in candidate_scores[:3]
        )

        related_files = sorted(
            group_index.get(
                (district, detail_sa, parsed.get("effdt"), parsed.get("rundt")),
                [detail_path.name],
            )
        )
        scaffold_rows.append(
            {
                "district": district,
                "sa": detail_sa or "",
                "detail_file": detail_path.name,
                "effdt": parsed.get("effdt") or "",
                "rundt": parsed.get("rundt") or "",
                "detail_unique_students": len(detail_keys["full_keys"]),
                "matched_batch_type": best["batch_type"] if selected else "UNKNOWN",
                "matched_batch_label": best["batch_label"] if selected else "Unknown",
                "matched_source_file": best["source_file"] if selected else "",
                "source_student_count": best["source_student_count"] if best else "",
                "full_overlap": best["full_overlap"] if best else "",
                "full_precision": best["full_precision"] if best else "",
                "full_recall": best["full_recall"] if best else "",
                "full_f1": best["full_f1"] if best else "",
                "relaxed_overlap": best["relaxed_overlap"] if best else "",
                "relaxed_precision": best["relaxed_precision"] if best else "",
                "relaxed_recall": best["relaxed_recall"] if best else "",
                "relaxed_f1": best["relaxed_f1"] if best else "",
                "size_delta": best["size_delta"] if best else "",
                "confidence": _selection_confidence(selection_reason, best),
                "selection_reason": selection_reason,
                "detail_encoding": encoding,
                "related_download_files": " | ".join(related_files),
                "top_candidates": top_candidates,
            }
        )

    output_path = output_path or (base_dir / "report_type_scaffold.csv")
    fieldnames = [
        "district",
        "sa",
        "detail_file",
        "effdt",
        "rundt",
        "detail_unique_students",
        "matched_batch_type",
        "matched_batch_label",
        "matched_source_file",
        "source_student_count",
        "full_overlap",
        "full_precision",
        "full_recall",
        "full_f1",
        "relaxed_overlap",
        "relaxed_precision",
        "relaxed_recall",
        "relaxed_f1",
        "size_delta",
        "confidence",
        "selection_reason",
        "detail_encoding",
        "related_download_files",
        "top_candidates",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scaffold_rows)

    return scaffold_rows


def _extract_zip_job(path):
    try:
        with zipfile.ZipFile(path) as zf:
            jobs = set()
            for name in zf.namelist():
                parsed = _parse_download_filename(Path(name).name)
                job = parsed.get("job")
                if job:
                    jobs.add(job)
            if len(jobs) == 1:
                return next(iter(jobs))
    except zipfile.BadZipFile:
        return None
    return None


def organize_results_by_type(
    download_date,
    scaffold_path=None,
    sorted_base=None,
    copy_unclassified=True,
):
    base_dir = Path("downloads") / download_date
    scaffold_path = Path(scaffold_path or (base_dir / "report_type_scaffold.csv"))
    sorted_base = Path(sorted_base or f"downloads/{download_date}_sorted")
    sorted_base.mkdir(parents=True, exist_ok=True)

    with scaffold_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    job_to_type = {}
    used_files = set()
    for row in rows:
        parsed = _parse_download_filename(row["detail_file"])
        job = parsed.get("job")
        if not job:
            continue
        job_to_type[(row["district"], job)] = row["matched_batch_type"]

        source_path = base_dir / row["district"] / row["detail_file"]
        dest_dir = sorted_base / row["matched_batch_type"] / row["district"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        if source_path.exists():
            shutil.copy2(source_path, dest_dir / source_path.name)
            used_files.add(source_path.resolve())

    for district_dir in sorted(path for path in base_dir.iterdir() if path.is_dir()):
        for path in sorted(p for p in district_dir.iterdir() if p.is_file() and p.suffix.lower() == ".zip"):
            job = _extract_zip_job(path)
            batch_type = job_to_type.get((district_dir.name, job))
            if batch_type is None:
                if not copy_unclassified:
                    continue
                batch_type = "UNCLASSIFIED"
            dest_dir = sorted_base / batch_type / district_dir.name
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest_dir / path.name)
            used_files.add(path.resolve())

    if copy_unclassified:
        for district_dir in sorted(path for path in base_dir.iterdir() if path.is_dir()):
            for path in sorted(p for p in district_dir.iterdir() if p.is_file()):
                if path.resolve() in used_files:
                    continue
                dest_dir = sorted_base / "UNCLASSIFIED" / district_dir.name
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest_dir / path.name)

    return {
        "sorted_base": str(sorted_base),
        "classified_rows": len(rows),
    }


def extract_migrant_districtwide_basic_reports(
    download_date,
    sorted_base=None,
    output_root="migrant_workflow",
    districts=None,
):
    sorted_base = Path(sorted_base or f"downloads/{download_date}_sorted/MIGRANT")
    output_root = Path(output_root)
    excel_dir = output_root / "data" / "excel"
    pdf_dir = output_root / "data" / "pdf"
    excel_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    district_filter = None
    if districts not in (None, "", []):
        district_filter = {str(d) for d in districts}

    extracted_rows = []
    for zip_path in sorted(sorted_base.glob("*/*.zip")):
        district = zip_path.parent.name
        if district_filter and district not in district_filter:
            continue

        zip_meta = _parse_download_filename(zip_path.name)
        with zipfile.ZipFile(zip_path) as zf:
            for member_name in zf.namelist():
                member_base = Path(member_name).name
                if not member_base:
                    continue
                member_meta = _parse_download_filename(member_base)
                if not member_meta.get("job"):
                    continue
                if _report_type_from_name(member_base) != "_Basic":
                    continue
                if member_meta.get("act") != member_meta.get("sa"):
                    continue

                suffix = Path(member_base).suffix.lower()
                if suffix not in {".xls", ".xlsx", ".pdf"}:
                    continue

                target_dir = excel_dir if suffix in {".xls", ".xlsx"} else pdf_dir
                target_name = f"NSC_{district}__Districtwide_Basic{suffix}"
                target_path = target_dir / target_name
                with zf.open(member_name) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                extracted_rows.append(
                    {
                        "district": district,
                        "zip_path": str(zip_path),
                        "member_name": member_base,
                        "job": member_meta.get("job") or "",
                        "effdt": zip_meta.get("effdt") or member_meta.get("effdt") or "",
                        "rundt": zip_meta.get("rundt") or member_meta.get("rundt") or "",
                        "output_path": str(target_path),
                    }
                )

    manifest_path = output_root / "migrant_districtwide_basic_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["district", "zip_path", "member_name", "job", "effdt", "rundt", "output_path"],
        )
        writer.writeheader()
        writer.writerows(extracted_rows)

    return {
        "output_root": str(output_root),
        "manifest_path": str(manifest_path),
        "extracted_count": len(extracted_rows),
    }


# Get list of files
def upload_requests(
    creds,
    request=False,
    run_date=None,
    state_base="state",
    force=False,
    dry_run=False,
    filename_prefixes=None,
    cohort_years=None,
):
    if cohort_years is None:
        raise ValueError(
            "cohort_years is required: request uploads must declare one or more "
            "classes and graduate submissions must declare exactly one class"
        )
    if request:
        validated_cohort_years = validate_request_cohort_years(
            cohort_years, context="StudentTracker request upload batch"
        )
    else:
        validated_cohort_years = validate_graduate_cohort_years(
            cohort_years, context="StudentTracker graduate submission upload batch"
        )
    run_date = run_date or date
    kind = "request" if request else "submission"
    state_dir = _state_dir(os.path.join(state_base, "uploads"), run_date, kind)
    if request == True:
        upload_dir = "requestfiles"
    else:
        upload_dir = "submissionfiles"

    for i in creds:
        safe_cred = {k: ("<redacted>" if k.lower() in {"pass", "password"} else v) for k, v in i.items()}
        print(safe_cred)
        submissionfiles = _matching_upload_files(
            upload_dir,
            i["sa"],
            filename_prefixes=filename_prefixes,
        )
        if not submissionfiles:
            print("No submission match")
            print("\n")
            continue

        pending_files = []
        for submission_file in submissionfiles:
            state_path = os.path.join(
                state_dir,
                f"{_safe_filename(i.get('user'))}__{_safe_filename(submission_file)}.json",
            )
            state = _load_state(state_path)
            if _should_skip_terminal_state(state, force):
                print(
                    f"Skipping {i.get('user')} ({state.get('status')}: {submission_file})"
                )
                continue
            pending_files.append((submission_file, state_path, state))

        if not pending_files:
            print("No pending uploads")
            print("\n")
            continue

        if dry_run:
            for submission_file, _, _ in pending_files:
                remotepath = f"/Home/{i['user']}/{submission_file}"
                print(
                    f"DRY RUN would upload {kind} file: {submission_file} -> {remotepath} "
                    f"(cohort_years={','.join(str(year) for year in validated_cohort_years)})"
                )
            print("\n")
            continue

        t = paramiko.transport.Transport(("ftps.nslc.org", 22))
        try:
            t.connect(username=i["user"], password=i["pass"])
        except paramiko.ssh_exception.AuthenticationException:
            print("Authentication failed")
            for submission_file, state_path, state in pending_files:
                state.update(
                    {
                        "status": "failed",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "filename": submission_file,
                        "error": "Authentication failed",
                    }
                )
                _save_state(state_path, state)
            t.close()
            print("\n")
            raise TransferAuthenticationError(
                f"Upload stopped after authentication failed for {i.get('district', 'account')}"
            ) from None
        except Exception as exc:
            error_class = type(exc).__name__
            for submission_file, state_path, state in pending_files:
                state.update({"status": "failed", "timestamp": datetime.datetime.now().isoformat(),
                              "filename": submission_file, "error": error_class})
                _save_state(state_path, state)
            t.close()
            raise RuntimeError(f"Upload connection failed: {error_class}") from None

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sftp = None
        try:
            sftp = paramiko.SFTPClient.from_transport(t)
            for submission_file, state_path, state in pending_files:
                print(submission_file)
                localpath = f"{upload_dir}/{submission_file}"
                remotepath = f"/Home/{i['user']}/{submission_file}"

                sftp.put(
                    localpath=localpath,
                    remotepath=remotepath,
                )
                local_size = os.path.getsize(localpath)
                remote_size = sftp.stat(remotepath).st_size
                if local_size != remote_size:
                    state.update(
                        {
                            "status": "failed",
                            "timestamp": datetime.datetime.now().isoformat(),
                            "filename": submission_file,
                            "error": f"Size mismatch local={local_size} remote={remote_size}",
                        }
                    )
                    _save_state(state_path, state)
                    raise RuntimeError("Upload size mismatch")

                state.update(
                    {
                        "status": "success",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "filename": submission_file,
                    }
                )
                state.pop("error", None)
                _save_state(state_path, state)
        except Exception as exc:
            error_class = type(exc).__name__
            # A connection/channel failure can affect every still-pending file.
            for failed_file, failed_path, failed_state in pending_files:
                if failed_state.get("status") == "success":
                    continue
                failed_state.update({"status": "failed", "timestamp": datetime.datetime.now().isoformat(),
                                     "filename": failed_file, "error": error_class})
                _save_state(failed_path, failed_state)
            raise RuntimeError(f"Upload transfer failed: {error_class}") from None
        finally:
            if sftp is not None:
                sftp.close()
            t.close()

        print("\n")


# Download files
# All available files are downloaded to a folder based on today's date.
# Additional filtering is required for the rename and sorting
def download_files(date, creds, state_base="state", force=False):
    base = os.path.join("downloads", date)
    os.makedirs(base, exist_ok=True)
    state_dir = _state_dir(os.path.join(state_base, "downloads"), date, "download")

    for c in creds:
        if c.get("sa") == "90000003":
            continue

        state_path = os.path.join(state_dir, f"{_safe_filename(c.get('user'))}.json")
        state = _load_state(state_path)
        if _should_skip_terminal_state(state, force):
            print(f"\n=== {c['district']} / {c['user']} === [SKIPPED - {state.get('status')}]")
            continue

        dst_dir = os.path.join(base, c["district"])
        os.makedirs(dst_dir, exist_ok=True)

        print(f"\n=== {c['district']} / {c['user']} ===")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # IMPORTANT: this must be SFTP (SSH). If this host is FTPS, this will not work.
            ssh.connect(
                hostname="ftps.nslc.org",  # confirm this is really the SFTP hostname
                port=22,
                username=c["user"],
                password=c["pass"],
                look_for_keys=False,
                allow_agent=False,
                timeout=30,
            )
        except paramiko.ssh_exception.AuthenticationException:
            print("Authentication failed; stopping download run")
            state.update(
                {
                    "status": "failed",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "error": "Authentication failed",
                }
            )
            _save_state(state_path, state)
            ssh.close()
            raise TransferAuthenticationError(
                f"Download stopped after authentication failed for {c.get('district', 'account')}"
            ) from None
        except Exception as e:
            error_class = type(e).__name__
            print(f"Connection failed: {error_class}")
            state.update(
                {
                    "status": "failed",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "error": error_class,
                }
            )
            _save_state(state_path, state)
            ssh.close()
            continue

        sftp = None
        try:
            sftp = ssh.open_sftp()
            # Every absolute fallback belongs to this login; never reuse another account's home.
            selected = _resolve_remote_dir(sftp, _receive_target_dirs(c["user"]))

            if not selected:
                raise RuntimeError(
                    "Could not find a usable 'receive' directory. "
                    "Try the absolute server path provided by the vendor."
                )

            # List with attrs so we can skip subdirs
            entries = sftp.listdir_attr(".")
            print("Found", len(entries), "entries")
            downloaded_files = []
            for e in entries:
                if stat.S_ISDIR(e.st_mode):
                    # skip directories
                    continue
                remote_name = e.filename
                local_path = os.path.join(dst_dir, remote_name)
                print("Downloading:", remote_name, "->", local_path)
                sftp.get(remote_name, local_path)
                downloaded_files.append(remote_name)

            # Record result in manifest
            if downloaded_files:
                state.update(
                    {
                        "status": "success",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "downloaded_files": downloaded_files,
                    }
                )
                state.pop("error", None)
            else:
                state.update(
                    {
                        "status": "empty",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "downloaded_files": [],
                    }
                )
                state.pop("error", None)
            _save_state(state_path, state)

        except Exception as exc:
            error_class = type(exc).__name__
            state.update({"status": "failed", "timestamp": datetime.datetime.now().isoformat(),
                          "error": error_class})
            _save_state(state_path, state)
            print(f"Download failed: {error_class}")
        finally:
            if sftp is not None:
                sftp.close()
            ssh.close()


# === Watermark helpers ===
def add_header_to_pdf(input_pdf, output_pdf, header_text):
    existing_pdf = PdfReader(input_pdf)
    output = PdfWriter()
    if existing_pdf.metadata:
        output.add_metadata(existing_pdf.metadata)

    for source_page in existing_pdf.pages:
        packet = io.BytesIO()

        # Normalize /Rotate into page content so the overlay coordinates match
        # the page's visible orientation.
        if source_page.rotation:
            source_page.transfer_rotation_to_content()
        page_width = float(source_page.mediabox.width)
        source_page_height = float(source_page.mediabox.height)
        header_band_height = 30.0
        page_height = source_page_height + header_band_height

        can = canvas.Canvas(packet, pagesize=(page_width, page_height))
        can.saveState()
        font_name = "Helvetica-Bold"
        font_size = 10.0
        max_width = page_width - 72.0
        while font_size > 6.0 and stringWidth(header_text, font_name, font_size) > max_width:
            font_size -= 0.5
        can.setFont(font_name, font_size)
        text_width = stringWidth(header_text, font_name, font_size)
        text_y = source_page_height + 10.0

        # Reserve a dedicated white strip above the vendor page. Some BASIC
        # covers paint an opaque logo to the original top edge and can obscure
        # a conventional PDF overlay in Poppler and other renderers.
        can.setFillColorRGB(1.0, 1.0, 1.0)
        can.rect(0.0, source_page_height, page_width, header_band_height, stroke=0, fill=1)
        can.setFillColorRGB(0.0, 0.0, 0.0)
        can.drawCentredString(page_width / 2.0, text_y, header_text)
        can.restoreState()
        can.save()

        packet.seek(0)
        new_pdf = PdfReader(packet)
        page = PageObject.create_blank_page(width=page_width, height=page_height)
        page.merge_page(source_page, over=True, expand=False)
        page.merge_page(new_pdf.pages[0], over=True, expand=False)
        output.add_page(page)

    temp_output = f"{output_pdf}.watermarking"
    try:
        with open(temp_output, "wb") as output_stream:
            output.write(output_stream)
        os.replace(temp_output, output_pdf)
    finally:
        if os.path.exists(temp_output):
            os.remove(temp_output)


def find_pdfs_and_add_header(directory, header_text):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".pdf"):
                input_pdf_path = os.path.join(root, file)
                output_pdf_path = os.path.join(root, file)
                add_header_to_pdf(input_pdf_path, output_pdf_path, header_text)
                print(f"Added header to {input_pdf_path}, saved as {output_pdf_path}")


# Work on processed copies: this helper filters/deletes nonmatching files there,
# extracts archives, and may overwrite PDFs. Preserve raw downloads and use exact batch scope.
def expand_and_rename(
    eff_date,
    suffix="",
    filter_rundt="",
    filter_effdt="",
    header_text=None,
    creds_override=None,
    comprehensive_only=True,
):
    creds_iter = creds_override if creds_override is not None else creds
    rundt_filters = _normalize_rundt_filters(filter_rundt)
    effdt_filters = _normalize_effdt_filters(filter_effdt)
    school_lookup = _build_school_lookup()
    for i in creds_iter:
        safe_cred = {
            k: ("<redacted>" if k.lower() in {"pass", "password"} else v)
            for k, v in i.items()
        }
        print(safe_cred)

        # NEW: copy downloads -> processed for this district/date
        src_folder = f"downloads/{eff_date}/{i['district']}"
        dest_folder = f"processed/{eff_date}/{i['district']}"
        if not os.path.isdir(src_folder):
            continue
        selected_download_names = None
        if comprehensive_only:
            selected_download_names = _select_comprehensive_download_names(
                src_folder,
                rundt_filters,
                effdt_filters,
            )
            if selected_download_names is None:
                print("No comprehensive DETAIL match")
                continue
            print(
                "Selected comprehensive files:",
                ", ".join(sorted(selected_download_names)),
            )
        try:
            os.makedirs(dest_folder, exist_ok=True)
            for name in os.listdir(src_folder):
                if (
                    selected_download_names is not None
                    and name not in selected_download_names
                ):
                    continue
                if not _matches_rundt_filter(name, rundt_filters):
                    continue
                if not _matches_effdt_filter(name, effdt_filters):
                    continue
                src_path = os.path.join(src_folder, name)
                dest_path = os.path.join(dest_folder, name)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dest_path)
                elif os.path.isdir(src_path):
                    # Merge directory contents
                    for root, _, files in os.walk(src_path):
                        rel = os.path.relpath(root, src_folder)
                        target_root = os.path.join(dest_folder, rel)
                        os.makedirs(target_root, exist_ok=True)
                        for f in files:
                            if not _matches_rundt_filter(f, rundt_filters):
                                continue
                            if not _matches_effdt_filter(f, effdt_filters):
                                continue
                            shutil.copy2(
                                os.path.join(root, f), os.path.join(target_root, f)
                            )
        except FileNotFoundError:
            # Nothing downloaded for this district/date
            pass

        # Continue with existing processing in the 'processed' folder
        dist_folder = dest_folder
        try:
            files = os.listdir(dist_folder)
        except UnboundLocalError:
            continue
        except FileNotFoundError:
            continue

        reports_dir = os.path.join(dist_folder, "reports")
        detail_dir = os.path.join(dist_folder, "detail")
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(detail_dir, exist_ok=True)

        # Move report files into reports_dir and unzip any zips
        for j in files:
            if j in {"reports", "detail"}:
                continue
            src_path = os.path.join(dist_folder, j)
            if os.path.isdir(src_path):
                continue
            if not _matches_rundt_filter(j, rundt_filters):
                continue
            if not _matches_effdt_filter(j, effdt_filters):
                continue
            if j.lower().endswith(".zip"):
                with zipfile.ZipFile(src_path, "r") as zipfile_ref:
                    zipfile_ref.extractall(reports_dir)
            elif j.lower().endswith((".pdf", ".xls", ".xlsx", ".csv")):
                target_dir = detail_dir if _is_detail_filename(j) else reports_dir
                _move_or_dedupe(src_path, os.path.join(target_dir, j))

        # Keep DETAIL CSVs separated from reports (PII isolation).
        for moved_name in sorted(os.listdir(reports_dir)):
            if not _is_detail_filename(moved_name):
                continue
            src_path = os.path.join(reports_dir, moved_name)
            if not os.path.isfile(src_path):
                continue
            _move_or_dedupe(src_path, os.path.join(detail_dir, moved_name))

        # Rename unzipped / report files
        report_files = sorted(os.listdir(reports_dir))
        for k in report_files:
            print(k)
            source_path = os.path.join(reports_dir, k)
            if not os.path.isfile(source_path):
                continue

            # Idempotency: once renamed, keep this file unchanged on reruns.
            if k.startswith("NSC_"):
                continue

            parsed = _VENDOR_REPORT_RE.match(k)
            if not parsed:
                continue

            sa_token = parsed.group("sa")
            if sa_token != str(i["sa"]).strip():
                raise ValueError("Report SA does not match the processing account")
            act_token = parsed.group("act")
            act_lookup = _normalize_act_token(act_token)
            if sa_token == i["sa"] and act_token == sa_token:
                school_name = "_Districtwide"
            else:
                school_name = school_lookup.get((sa_token, act_lookup))
                if school_name is None:
                    school_name = f"_ACT{act_lookup}"

            report_type = _report_type_from_name(k)
            batch_tag = _extract_batch_tag(k)
            ext = os.path.splitext(k)[1]
            dest_name = (
                f"NSC_{i['district']}_{school_name}{report_type}{suffix}{batch_tag}{ext}"
            )
            dest_path = os.path.join(reports_dir, dest_name)

            # Duplicate-safe reruns: same raw source can be seen more than once.
            if os.path.exists(dest_path):
                if _files_identical(source_path, dest_path):
                    os.remove(source_path)
                    continue
                dest_path = _next_available_path(dest_path)

            os.rename(source_path, dest_path)

        # Rename DETAIL CSVs in a separate folder so PII is not mixed with reports.
        detail_files = sorted(os.listdir(detail_dir))
        for k in detail_files:
            print(k)
            source_path = os.path.join(detail_dir, k)
            if not os.path.isfile(source_path):
                continue
            if k.startswith("NSC_"):
                continue
            if not _is_detail_filename(k):
                continue

            parsed = _DETAIL_FILE_RE.match(k)
            if not parsed:
                continue

            sa_token = parsed.group("sa")
            if sa_token != str(i["sa"]).strip():
                raise ValueError("DETAIL SA does not match the processing account")
            job_token = parsed.group("job")
            batch_tag = _extract_batch_tag(k)
            ext = os.path.splitext(k)[1]
            dest_name = (
                f"NSC_{i['district']}_Detail_{sa_token}_{job_token}{suffix}{batch_tag}{ext}"
            )
            dest_path = os.path.join(detail_dir, dest_name)

            if os.path.exists(dest_path):
                if _files_identical(source_path, dest_path):
                    os.remove(source_path)
                    continue
                dest_path = _next_available_path(dest_path)

            os.rename(source_path, dest_path)

        # Optional: watermark PDFs after renaming.
        if header_text and os.path.isdir(reports_dir):
            find_pdfs_and_add_header(reports_dir, header_text)

        # Always zip renamed report files (reports only; detail files excluded).
        if os.path.isdir(reports_dir):
            report_file_count = sum(
                len(files) for _, _, files in os.walk(reports_dir)
            )
            if report_file_count > 0:
                zip_out = os.path.join(
                    dist_folder,
                    _renamed_zip_name(i["district"], suffix),
                )
                with zipfile.ZipFile(
                    zip_out, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    for root, _, files in os.walk(reports_dir):
                        for fname in files:
                            path = os.path.join(root, fname)
                            arcname = os.path.relpath(path, reports_dir)
                            zf.write(path, arcname)
                print(f"Created {zip_out}")


# Main function
if __name__ == "__main__":
    # # Example usage:
    # today = '20251222'
    # # download_files(date = today, creds = creds)
    # expand_and_rename(
    #     eff_date = today
    # )
    # # expand_and_rename(
    # #     date,
    # #     suffix="_SealOfBiliteracy",
    # #     header_text="Seal of Biliteracy Only Student Report - NOT ALL GRADUATES",
    # # )
    pass
