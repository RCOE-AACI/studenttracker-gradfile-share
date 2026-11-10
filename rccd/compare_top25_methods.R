# Compare RCCD/NSC college summaries to diagnose aggregation differences; requires private local inputs.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(dplyr)
library(readr)
library(stringr)

get_latest_processed_eff_date <- function(processed_root = "processed") {
  dirs <- list.dirs(processed_root, recursive = FALSE, full.names = FALSE)
  dirs <- dirs[str_detect(dirs, "^\\d{8}$")]
  if (length(dirs) == 0) stop(sprintf("No processed eff_date folders found under %s", processed_root))
  sort(dirs, decreasing = TRUE)[[1]]
}

parse_top25 <- function(path, cohort_year, college_ids = NULL) {
  df <- suppressMessages(read_csv(path, col_types = cols(.default = col_character())))
  required <- c("Cohort", "College ID", "Count")
  if (!all(required %in% names(df))) return(tibble())

  df <- df %>%
    mutate(
      Cohort = as.integer(Cohort),
      Count = suppressWarnings(as.integer(Count))
    ) %>%
    filter(Cohort == cohort_year)

  if (!is.null(college_ids)) {
    df <- df %>% filter(`College ID` %in% college_ids)
  }

  df
}

sum_by_district_college <- function(paths, cohort_year, college_ids = NULL) {
  bind_rows(lapply(paths, function(path) {
    district <- basename(dirname(dirname(path)))
    school_file <- basename(path)
    parse_top25(path, cohort_year = cohort_year, college_ids = college_ids) %>%
      mutate(District = district, file = school_file)
  })) %>%
    group_by(District, `College ID`, `College Name`) %>%
    summarise(students = sum(Count, na.rm = TRUE), files_with_college = n_distinct(file), .groups = "drop")
}

EFF_DATE <- Sys.getenv("EFF_DATE", unset = NA_character_)
if (is.na(EFF_DATE) || !dir.exists(file.path("processed", EFF_DATE))) {
  EFF_DATE <- get_latest_processed_eff_date()
}

COHORT_YEAR <- as.integer(Sys.getenv("COHORT_YEAR", unset = "2025"))
college_ids_env <- Sys.getenv("COLLEGE_IDS", unset = "001270-00,041735-00,041761-00")
COLLEGE_IDS <- str_split(college_ids_env, ",", simplify = TRUE)
COLLEGE_IDS <- str_trim(as.character(COLLEGE_IDS))
COLLEGE_IDS <- COLLEGE_IDS[COLLEGE_IDS != ""]

root <- file.path("processed", EFF_DATE)

districtwide_reports <- list.files(root, pattern = "Districtwide_Top25\\.csv$", recursive = TRUE, full.names = TRUE)
districtwide_reports <- districtwide_reports[str_detect(districtwide_reports, "/reports/")]

school_reports <- list.files(root, pattern = "Top25\\.csv$", recursive = TRUE, full.names = TRUE)
school_reports <- school_reports[str_detect(school_reports, "/reports/")]
school_reports <- school_reports[!str_detect(school_reports, "Districtwide_Top25\\.csv$")]

districtwide_orts <- list.files(root, pattern = "Districtwide_Top25\\.csv$", recursive = TRUE, full.names = TRUE)
districtwide_orts <- districtwide_orts[str_detect(districtwide_orts, "orts/")]

school_orts <- list.files(root, pattern = "Top25\\.csv$", recursive = TRUE, full.names = TRUE)
school_orts <- school_orts[str_detect(school_orts, "orts/")]
school_orts <- school_orts[!str_detect(school_orts, "Districtwide_Top25\\.csv$")]

dw_reports <- sum_by_district_college(districtwide_reports, cohort_year = COHORT_YEAR, college_ids = COLLEGE_IDS) %>%
  mutate(method = "districtwide_reports")
sc_reports <- sum_by_district_college(school_reports, cohort_year = COHORT_YEAR, college_ids = COLLEGE_IDS) %>%
  mutate(method = "school_sum_reports")

dw_reports_orts <- sum_by_district_college(c(districtwide_reports, districtwide_orts), cohort_year = COHORT_YEAR, college_ids = COLLEGE_IDS) %>%
  mutate(method = "districtwide_reports_plus_orts")
sc_reports_orts <- sum_by_district_college(c(school_reports, school_orts), cohort_year = COHORT_YEAR, college_ids = COLLEGE_IDS) %>%
  mutate(method = "school_sum_reports_plus_orts")

compare <- dw_reports %>%
  rename(districtwide_students = students, districtwide_files = files_with_college) %>%
  full_join(
    sc_reports %>% rename(school_students = students, school_files = files_with_college),
    by = c("District", "College ID", "College Name")
  ) %>%
  mutate(
    districtwide_students = coalesce(districtwide_students, 0L),
    school_students = coalesce(school_students, 0L),
    diff_students = school_students - districtwide_students,
    diff_pct = if_else(districtwide_students == 0, NA_real_, diff_students / districtwide_students)
  ) %>%
  arrange(desc(abs(diff_students)))

compare_orts <- dw_reports_orts %>%
  rename(districtwide_students = students, districtwide_files = files_with_college) %>%
  full_join(
    sc_reports_orts %>% rename(school_students = students, school_files = files_with_college),
    by = c("District", "College ID", "College Name")
  ) %>%
  mutate(
    districtwide_students = coalesce(districtwide_students, 0L),
    school_students = coalesce(school_students, 0L),
    diff_students = school_students - districtwide_students,
    diff_pct = if_else(districtwide_students == 0, NA_real_, diff_students / districtwide_students)
  ) %>%
  arrange(desc(abs(diff_students)))

out_compare <- file.path(root, sprintf("_top25_method_compare_cohort%s.csv", COHORT_YEAR))
out_compare_orts <- file.path(root, sprintf("_top25_method_compare_cohort%s_including_orts.csv", COHORT_YEAR))

write_csv(compare, out_compare)
write_csv(compare_orts, out_compare_orts)

message(sprintf("Wrote: %s", out_compare))
message(sprintf("Wrote: %s", out_compare_orts))

totals <- compare %>%
  summarise(
    districtwide_students = sum(districtwide_students),
    school_students = sum(school_students),
    diff_students = sum(diff_students),
    .groups = "drop"
  )

totals_orts <- compare_orts %>%
  summarise(
    districtwide_students = sum(districtwide_students),
    school_students = sum(school_students),
    diff_students = sum(diff_students),
    .groups = "drop"
  )

message("Totals (reports-only):")
print(totals)
message("Totals (including *orts):")
print(totals_orts)

