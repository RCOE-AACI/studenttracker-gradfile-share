#!/usr/bin/env Rscript
# R AVID implementation and contract helpers. New single-class requests use the maintained Python generator. REQ-24, REQ-29.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.

suppressPackageStartupMessages({
  library(arrow)
  library(digest)
  library(dplyr)
  library(lubridate)
  library(readr)
  library(readxl)
  library(stringi)
  library(stringr)
  library(tibble)
})

REQUEST_FIELD_COUNT <- 25L
AVID_STATE_COURSE <- "9211"
MISSING_TEXT_TOKENS <- c("NA", "N/A", "NULL", "Null", "null", "NONE", "None", "none")

plain_character <- function(x) {
  if (is.numeric(x)) {
    return(format(x, scientific = FALSE, trim = TRUE))
  }
  as.character(x)
}

blank_na_text <- function(x) {
  value <- plain_character(x)
  value[is.na(value)] <- ""
  str_trim(value)
}

blank_missing_text <- function(x) {
  value <- blank_na_text(x)
  missing_tokens <- value %in% MISSING_TEXT_TOKENS
  value[missing_tokens] <- ""
  value
}

normalize_ssid <- function(x) {
  plain_character(x) |>
    str_trim() |>
    str_remove_all("_") |>
    str_remove("\\.0$")
}

normalize_account_code <- function(x, width) {
  value <- blank_missing_text(x) |>
    str_remove("\\.0$") |>
    str_trim()
  numeric_code <- str_detect(value, "^[0-9]+$")
  value[numeric_code] <- str_pad(value[numeric_code], width = width, side = "left", pad = "0")
  value
}

sanitize_text <- function(x) {
  x |>
    blank_na_text() |>
    stri_trans_general("Latin-ASCII") |>
    str_replace_all("[\\t\\r\\n]+", " ") |>
    str_replace_all("\\.", "") |>
    str_squish()
}

sanitize_optional_name <- function(x) {
  x |>
    blank_missing_text() |>
    stri_trans_general("Latin-ASCII") |>
    str_replace_all("[\\t\\r\\n]+", " ") |>
    str_replace_all("\\.", "") |>
    str_squish()
}

filename_token <- function(x) {
  sanitize_text(x) |>
    str_to_upper() |>
    str_replace_all("[^A-Z0-9-]+", "")
}

format_nsc_date <- function(x) {
  if (inherits(x, "Date")) {
    return(format(x, "%Y%m%d"))
  }
  if (inherits(x, "POSIXt")) {
    return(format(as.Date(x), "%Y%m%d"))
  }
  raw <- blank_missing_text(x)
  parsed <- suppressWarnings(ymd(raw, quiet = TRUE))
  missing <- is.na(parsed) & raw != ""
  if (any(missing)) {
    parsed[missing] <- suppressWarnings(mdy(raw[missing], quiet = TRUE))
  }
  ifelse(is.na(parsed), "", format(parsed, "%Y%m%d"))
}

report_window <- function(report_year, cohort_year) {
  parts <- str_split(report_year, "-", simplify = TRUE)
  if (ncol(parts) != 2L || any(!str_detect(parts, "^[0-9]{4}$"))) {
    stop("--report-year must use YYYY-YYYY")
  }
  start_year <- as.integer(parts[[1]])
  end_year <- as.integer(parts[[2]])
  if (end_year != start_year + 1L || cohort_year != end_year) {
    stop("--report-year must be consecutive and end in --cohort-year")
  }
  list(
    start = as.Date(paste0(start_year, "-09-01")),
    end = as.Date(paste0(end_year, "-08-31"))
  )
}

yes_no <- function(x) {
  case_when(
    x == "Yes" ~ "Y",
    x == "No" ~ "N",
    TRUE ~ ""
  )
}

race_code <- function(x) {
  case_when(
    x == "African American" ~ "BL",
    x %in% c("Asian", "Filipino") ~ "AS",
    x == "Native American" ~ "AM",
    x == "Pacific Islander" ~ "PI",
    x == "Two or More" ~ "MU",
    x == "White" ~ "WH",
    x == "Hispanic" ~ "HI",
    TRUE ~ ""
  )
}

build_request_body <- function(rows) {
  rows |>
    transmute(
      A = "D3",
      B = "",
      C = sanitize_text(FirstName),
      D = sanitize_optional_name(MiddleName),
      E = sanitize_text(LastName),
      F = sanitize_optional_name(Suffix),
      G = format_nsc_date(BirthDate),
      H = format_nsc_date(StudentEnrollmentExitDate),
      I = sanitize_text(ACT),
      J = "",
      K = "",
      L = normalize_ssid(SSID),
      M = if_else(Gender %in% c("M", "F"), Gender, ""),
      N = race_code(EthnicityRace),
      O = yes_no(SocioEconomicallyDisadvantaged),
      P = "",
      Q = "",
      R = "",
      S = "",
      T = yes_no(EnglishLearner),
      U = "",
      V = "",
      W = yes_no(StudentswithDisabilities),
      X = paste(
        if_else(MigrantEd == "Yes", "MIG_Y", "MIG_N"),
        if_else(FosterYouth == "Yes", "FOS_Y", "FOS_N"),
        if_else(Homeless == "Yes", "HOM_Y", "HOM_N"),
        if_else(UC_CSURequirementsMet == "Yes", "AG_Y", "AG_N"),
        if_else(Sealofbiliteracy == "Yes", "SSB_Y", "SSB_N"),
        sep = "."
      ),
      Y = "ED"
    )
}

hash_file <- function(path) {
  digest(path, algo = "sha256", file = TRUE, serialize = FALSE)
}

install_temp_file <- function(temp_path, path, allow_overwrite = FALSE) {
  if (file.exists(path)) {
    if (identical(hash_file(temp_path), hash_file(path))) {
      unlink(temp_path)
      return(invisible("unchanged"))
    }
    if (!allow_overwrite) {
      unlink(temp_path)
      stop("Refusing to overwrite a different existing file: ", path)
    }
    unlink(path)
  }
  if (!file.rename(temp_path, path)) {
    stop("Could not atomically install output: ", path)
  }
  invisible("written")
}

write_lines_atomic <- function(path, lines, allow_overwrite = FALSE) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  temp_path <- tempfile(pattern = paste0(basename(path), "."), tmpdir = dirname(path))
  writeLines(lines, temp_path, useBytes = TRUE)
  install_temp_file(temp_path, path, allow_overwrite)
}

write_csv_atomic <- function(data, path, allow_overwrite = FALSE) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  temp_path <- tempfile(pattern = paste0(basename(path), "."), tmpdir = dirname(path))
  write_csv(data, temp_path, na = "")
  install_temp_file(temp_path, path, allow_overwrite)
}

request_lines <- function(sa, district, run_date, body) {
  header <- paste(c("H3", sa, "", district, run_date, "SE", "D"), collapse = "\t")
  body_lines <- apply(
    body,
    1,
    function(row) paste(ifelse(is.na(row), "", row), collapse = "\t")
  )
  trailer <- paste(c("T3", nrow(body) + 2L), collapse = "\t")
  c(header, body_lines, trailer)
}

validate_request_file <- function(path, expected_sa, expected_students, run_date) {
  lines <- readLines(path, warn = FALSE)
  if (length(lines) != expected_students + 2L) {
    stop("Unexpected line count in ", path)
  }
  header <- strsplit(lines[[1]], "\t", fixed = TRUE)[[1]]
  trailer <- strsplit(lines[[length(lines)]], "\t", fixed = TRUE)[[1]]
  if (length(header) != 7L || header[[1]] != "H3" || header[[2]] != expected_sa || header[[5]] != run_date) {
    stop("Invalid H3 header in ", path)
  }
  if (length(trailer) != 2L || trailer[[1]] != "T3" || as.integer(trailer[[2]]) != expected_students + 2L) {
    stop("Invalid T3 trailer in ", path)
  }
  if (expected_students > 0L) {
    body_fields <- strsplit(lines[2:(length(lines) - 1L)], "\t", fixed = TRUE)
    if (any(lengths(body_fields) != REQUEST_FIELD_COUNT)) {
      stop("Invalid D3 field count in ", path)
    }
    if (any(vapply(body_fields, `[[`, character(1), 1L) != "D3")) {
      stop("Invalid D3 record type in ", path)
    }
    identifiers <- vapply(body_fields, `[[`, character(1), 12L)
    if (any(!str_detect(identifiers, "^[0-9]{10}$"))) {
      stop("Invalid raw SSID in ", path)
    }
    optional_name_values <- c(
      vapply(body_fields, `[[`, character(1), 4L),
      vapply(body_fields, `[[`, character(1), 6L)
    )
    if (any(str_trim(optional_name_values) %in% MISSING_TEXT_TOKENS)) {
      stop("Missing-value placeholder found in middle-name or suffix field in ", path)
    }
  }
  invisible(TRUE)
}

argument_value <- function(args, name, default) {
  index <- match(paste0("--", name), args)
  if (is.na(index)) {
    return(default)
  }
  if (index == length(args)) {
    stop("Missing value for --", name)
  }
  args[[index + 1L]]
}

main <- function(args = commandArgs(trailingOnly = TRUE)) {
  stop(
    paste(
      "Single-class AVID request generation is disabled.",
      "Use: ENV=prod uv run python 01x-process_avid_request.py",
      "--cohort-years 2022-2025"
    )
  )
  run_date <- argument_value(args, "run-date", format(Sys.Date(), "%Y%m%d"))
  cohort_year <- as.integer(argument_value(args, "cohort-year", "2025"))
  report_year <- argument_value(args, "report-year", "2024-2025")
  course_path <- argument_value(
    args,
    "course-file",
    file.path("data", paste0(report_year, "_311_snap.parquet"))
  )
  cohort_path <- argument_value(args, "cohort-file", "county_grad_w_accounts.rds")
  account_ref_path <- argument_value(args, "account-ref-file", file.path("data", "account_refs.xlsx"))
  allow_overwrite <- "--allow-overwrite" %in% args

  if (!str_detect(run_date, "^[0-9]{8}$")) {
    stop("--run-date must use YYYYMMDD")
  }
  window <- report_window(report_year, cohort_year)
  if (!file.exists(course_path) || !file.exists(cohort_path) || !file.exists(account_ref_path)) {
    stop("Required AVID input is missing")
  }

  course <- read_parquet(course_path, col_select = c("SSID", "StateCourse", "DistrictCode", "School_Code"))
  required_course <- c("SSID", "StateCourse", "DistrictCode", "School_Code")
  if (!all(required_course %in% names(course))) {
    stop("3.11 schema drift: required columns are missing")
  }
  avid_source <- course |>
    mutate(SSID = normalize_ssid(SSID)) |>
    filter(str_detect(StateCourse, paste0("^", AVID_STATE_COURSE, "(?:-|$)")), SSID != "")
  avid_ssids <- avid_source |>
    distinct(SSID)

  account_ref_raw <- read_excel(account_ref_path)
  required_account_ref <- c("CDS", "SA", "ACT", "District", "HSName")
  missing_account_ref_columns <- setdiff(required_account_ref, names(account_ref_raw))
  if (length(missing_account_ref_columns) > 0L) {
    stop("Account-reference schema drift: missing ", paste(missing_account_ref_columns, collapse = ", "))
  }
  account_ref <- account_ref_raw |>
    transmute(
      CDS = normalize_account_code(CDS, 14L),
      RefSA = normalize_account_code(SA, 8L),
      RefACT = normalize_account_code(ACT, 6L),
      RefDistrict = sanitize_text(District),
      RefHSName = sanitize_text(HSName)
    ) |>
    filter(CDS != "")
  if (anyDuplicated(account_ref$CDS) > 0L) {
    stop("Account-reference schema drift: duplicate nonblank CDS values")
  }

  cohort <- readRDS(cohort_path)
  required_cohort <- c(
    "SSID", "CohortYear", "StudentCompletionStatus", "FirstName", "MiddleName",
    "LastName", "Suffix", "BirthDate", "StudentEnrollmentExitDate", "CDS", "ACT", "SA",
    "District", "Gender", "EthnicityRace", "SocioEconomicallyDisadvantaged",
    "EnglishLearner", "StudentswithDisabilities", "MigrantEd", "FosterYouth",
    "Homeless", "UC_CSURequirementsMet", "Sealofbiliteracy"
  )
  missing_columns <- setdiff(required_cohort, names(cohort))
  if (length(missing_columns) > 0L) {
    stop("Cohort schema drift: missing ", paste(missing_columns, collapse = ", "))
  }

  candidates <- cohort |>
    mutate(
      SSID = normalize_ssid(SSID),
      CDS = normalize_account_code(CDS, 14L),
      CachedSA = normalize_account_code(SA, 8L),
      CachedACT = normalize_account_code(ACT, 6L),
      CohortYear = as.integer(plain_character(CohortYear)),
      StudentCompletionStatus = plain_character(StudentCompletionStatus),
      ExitDateParsed = as.Date(format_nsc_date(StudentEnrollmentExitDate), format = "%Y%m%d")
    ) |>
    filter(
      CohortYear == cohort_year,
      StudentCompletionStatus == "100",
      SSID %in% avid_ssids$SSID
    ) |>
    arrange(SSID) |>
    distinct(SSID, .keep_all = TRUE) |>
    left_join(account_ref, by = "CDS") |>
    mutate(
      AccountReferenceMatched = !is.na(RefSA),
      SA = coalesce(RefSA, ""),
      ACT = coalesce(RefACT, ""),
      District = coalesce(RefDistrict, ""),
      HSName = coalesce(RefHSName, "")
    ) |>
    arrange(SA, SSID)

  if (nrow(candidates) == 0L) {
    stop("No AVID students matched the configured graduate cohort")
  }
  if (anyDuplicated(candidates$SSID) > 0L) {
    stop("Duplicate SSIDs remain after AVID cohort selection")
  }

  for (column in c("Gender", "EthnicityRace", "SocioEconomicallyDisadvantaged", "EnglishLearner", "StudentswithDisabilities")) {
    values <- str_trim(plain_character(candidates[[column]]))
    if (all(is.na(values) | values == "")) {
      stop("Demographic schema drift: all candidate values are blank for ", column)
    }
  }

  prepared <- candidates |>
    mutate(
      FirstNameOut = sanitize_text(FirstName),
      LastNameOut = sanitize_text(LastName),
      BirthDateOut = format_nsc_date(BirthDate),
      ExitDateOut = format_nsc_date(StudentEnrollmentExitDate),
      DistrictOut = sanitize_text(District),
      HSNameOut = sanitize_text(HSName),
      BlockerReason = paste0(
        if_else(!AccountReferenceMatched, "unmatched_account_reference;", ""),
        if_else(!str_detect(SSID, "^[0-9]{10}$"), "invalid_ssid;", ""),
        if_else(FirstNameOut == "", "missing_first_name;", ""),
        if_else(LastNameOut == "", "missing_last_name;", ""),
        if_else(BirthDateOut == "", "missing_birth_date;", ""),
        if_else(ExitDateOut == "", "missing_exit_date;", ""),
        if_else(
          !is.na(ExitDateParsed) & (ExitDateParsed < window$start | ExitDateParsed > window$end),
          "outside_graduation_window;",
          ""
        ),
        if_else(SA == "", "missing_service_account;", ""),
        if_else(ACT == "", "missing_act;", ""),
        if_else(DistrictOut == "", "missing_district;", ""),
        if_else(HSNameOut == "", "missing_high_school;", "")
      ) |> str_remove(";$")
    )

  blockers <- prepared |>
    filter(BlockerReason != "") |>
    select(SSID, District, SA, BlockerReason)
  ready <- prepared |>
    filter(BlockerReason == "")

  audit_dir <- "audit"
  blocker_path <- file.path(audit_dir, paste0(run_date, "_avid_request_blockers.csv"))
  summary_path <- file.path(audit_dir, paste0(run_date, "_avid_request_summary.csv"))
  manifest_path <- file.path(audit_dir, paste0(run_date, "_avid_request_manifest.csv"))
  upload_manifest_path <- file.path(audit_dir, paste0(run_date, "_avid_request_upload_manifest.csv"))
  write_csv_atomic(blockers, blocker_path, allow_overwrite)
  if (nrow(ready) == 0L) {
    stop("All AVID candidates were blocked")
  }

  manifest_rows <- list()
  groups <- ready |>
    distinct(SA, District) |>
    arrange(District, SA)

  for (index in seq_len(nrow(groups))) {
    sa <- groups$SA[[index]]
    district <- groups$District[[index]]
    group_rows <- ready |>
      filter(SA == sa, District == district) |>
      arrange(SSID)
    body <- build_request_body(group_rows)
    district_token <- filename_token(district)

    request_path <- file.path(
      "requestfiles",
      paste0(run_date, "_", sa, "_", district_token, "_AVID.txt")
    )
    write_lines_atomic(
      request_path,
      request_lines(sa, district, run_date, body),
      allow_overwrite
    )
    validate_request_file(request_path, sa, nrow(body), run_date)

    test_body <- body |> slice_head(n = min(800L, nrow(body)))
    test_path <- file.path(
      "requestfiles", "test_file",
      paste0(run_date, "_", sa, "_", district_token, "_AVID.txt")
    )
    write_lines_atomic(
      test_path,
      request_lines(sa, district, run_date, test_body),
      allow_overwrite
    )
    validate_request_file(test_path, sa, nrow(test_body), run_date)

    manifest_rows[[length(manifest_rows) + 1L]] <- tibble(
      kind = "request",
      district = district,
      sa = sa,
      student_count = nrow(body),
      path = request_path,
      bytes = file.info(request_path)$size,
      sha256 = hash_file(request_path)
    )
    manifest_rows[[length(manifest_rows) + 1L]] <- tibble(
      kind = "test",
      district = district,
      sa = sa,
      student_count = nrow(test_body),
      path = test_path,
      bytes = file.info(test_path)$size,
      sha256 = hash_file(test_path)
    )
  }

  manifest <- bind_rows(manifest_rows) |>
    arrange(kind, district, sa)
  upload_manifest <- manifest |>
    filter(kind == "request")
  summary <- tibble(
    run_date = run_date,
    report_year = report_year,
    cohort_year = cohort_year,
    graduation_window_start = format(window$start),
    graduation_window_end = format(window$end),
    state_course = AVID_STATE_COURSE,
    source_311_rows = nrow(course),
    source_avid_rows = nrow(avid_source),
    source_avid_unique_ssids = nrow(avid_ssids),
    source_avid_districts = n_distinct(avid_source$DistrictCode),
    graduate_candidates = nrow(candidates),
    unmatched_account_reference_rows = sum(!candidates$AccountReferenceMatched),
    refreshed_sa_rows = sum(candidates$AccountReferenceMatched & candidates$CachedSA != candidates$SA),
    refreshed_act_rows = sum(candidates$AccountReferenceMatched & candidates$CachedACT != candidates$ACT),
    blocker_rows = nrow(blockers),
    outbound_students = nrow(ready),
    blank_middle_names = sum(sanitize_optional_name(ready$MiddleName) == ""),
    blank_suffixes = sum(sanitize_optional_name(ready$Suffix) == ""),
    service_accounts = nrow(groups),
    request_files = sum(manifest$kind == "request"),
    test_files = sum(manifest$kind == "test"),
    upload_bytes = sum(upload_manifest$bytes),
    course_file = course_path,
    course_file_sha256 = hash_file(course_path),
    cohort_file = cohort_path,
    cohort_file_sha256 = hash_file(cohort_path),
    account_ref_file = account_ref_path,
    account_ref_file_sha256 = hash_file(account_ref_path)
  )
  write_csv_atomic(summary, summary_path, allow_overwrite)
  write_csv_atomic(manifest, manifest_path, allow_overwrite)
  write_csv_atomic(upload_manifest, upload_manifest_path, allow_overwrite)

  cat(
    paste0(
      "AVID preflight complete: candidates=", nrow(candidates),
      ", blockers=", nrow(blockers),
      ", outbound=", nrow(ready),
      ", accounts=", nrow(groups),
      ", request_files=", sum(manifest$kind == "request"),
      ", test_files=", sum(manifest$kind == "test"),
      "\n"
    )
  )
}

if (sys.nframe() == 0L) {
  main()
}
