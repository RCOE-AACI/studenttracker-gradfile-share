# Combine normalized RCCD terms into the local consolidated input consumed by detail enrichment. REQ-16, DEC-04.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(arrow)
library(dplyr)
library(readr)

source("rccd/ingest_terms.R")
source("rccd/match_to_sinf.R")

rccd_build_consolidated <- function(
    rccd_root = "data/RCCD",
    sinf_path = "data/cumulative_sinf.parquet",
    out_path = "data/rccd_matched_ssid.parquet",
    crosswalk_path = "data/rccd_college_id_ssid_crosswalk.parquet",
    overrides_path = "data/rccd_match_overrides.csv",
    candidates_out_path = "data/rccd_match_candidates.parquet",
    qc_out_path = "data/rccd_match_qc.csv",
    cohort_years = Sys.getenv("COHORT_YEAR", unset = "2025"),
    submission_roots = Sys.getenv("SUBMISSION_ROOTS", unset = "submissionfiles")
) {
  rccd_all <- rccd_read_all_terms(rccd_root)

  crosswalk <- rccd_load_crosswalk(crosswalk_path)
  rccd_all <- rccd_apply_crosswalk(rccd_all, crosswalk)

  dob_values <- lubridate::ymd(rccd_all[["Date of Birth"]]) %>% unique()
  dob_values <- dob_values[!is.na(dob_values)]
  cohort_years <- strsplit(as.character(cohort_years), ",")[[1]]
  cohort_years <- trimws(cohort_years)
  submission_roots <- strsplit(as.character(submission_roots), ",")[[1]]
  submission_roots <- trimws(submission_roots)

  reference <- reference_load(
    cohort_years = cohort_years,
    submission_roots = submission_roots,
    sinf_path = sinf_path,
    dob_values = dob_values
  )

  match_res <- rccd_fuzzy_match_new_ids(rccd_all, reference)
  rccd_matched <- match_res$rccd

  overrides <- rccd_load_overrides(overrides_path)
  if (!is.null(overrides)) {
    rccd_matched <- rccd_apply_overrides(rccd_matched, overrides)
  }

  crosswalk_updated <- rccd_update_crosswalk(rccd_matched, crosswalk)

  qc <- rccd_matched %>%
    group_by(.data[["Academic Term"]]) %>%
    summarise(
      rows_total = n(),
      distinct_college_student_id = n_distinct(.data[["College Student ID"]]),
      distinct_ssid_matched = n_distinct(.data[["SSID"]], na.rm = TRUE),
      pct_ssid_missing = mean(is.na(.data[["SSID"]])),
      .groups = "drop"
    ) %>%
    arrange(.data[["Academic Term"]])

  write_parquet(rccd_matched, out_path, compression = "snappy")
  write_parquet(crosswalk_updated, crosswalk_path, compression = "snappy")
  if (nrow(match_res$candidates) > 0) {
    write_parquet(match_res$candidates, candidates_out_path, compression = "snappy")
  }
  write_csv(qc, qc_out_path)

  print(qc)
  invisible(list(rccd = rccd_matched, crosswalk = crosswalk_updated, qc = qc))
}

if (sys.nframe() == 0) {
  rccd_build_consolidated()
}
