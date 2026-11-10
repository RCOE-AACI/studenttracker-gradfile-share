# REQ-01 / REQ-25 / DEC-28: keep annual dates and source selection together.
# Defaults retain the source project's Class 2025. A new year must be selected explicitly.
annual_submission_config <- function(
  cohort_year = Sys.getenv("ST_COHORT_YEAR", "2025"),
  cohort_path = Sys.getenv("ST_COHORT_PATH", ""),
  run_date = Sys.getenv("ST_RUN_DATE", format(Sys.Date(), "%Y%m%d"))
) {
  if (!grepl("^20[0-9]{2}$", as.character(cohort_year))) {
    stop("ST_COHORT_YEAR must be a four-digit graduation class year")
  }
  cohort_year <- as.integer(cohort_year)
  if (!grepl("^[0-9]{8}$", run_date) ||
      is.na(as.Date(run_date, format = "%Y%m%d")) ||
      format(as.Date(run_date, format = "%Y%m%d"), "%Y%m%d") != run_date) {
    stop("ST_RUN_DATE must be a valid YYYYMMDD date")
  }
  if (!nzchar(cohort_path)) {
    cohort_path <- sprintf("data/ClassOf%02d-ClassOf%02d_152_cohort_outcomes.parquet",
                           cohort_year %% 100L, (cohort_year + 3L) %% 100L)
  }
  list(cohort_year = cohort_year, cohort_path = cohort_path,
       window_start = as.Date(sprintf("%s-09-01", cohort_year - 1L)),
       window_end = as.Date(sprintf("%s-08-31", cohort_year)),
       school_year = sprintf("%s-%s", cohort_year - 1L, cohort_year),
       run_date = run_date,
       excluded_districts = c("3367199", "3367231", "3367116"))
}
