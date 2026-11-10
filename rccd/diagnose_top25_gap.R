# Diagnose differences between college summary methods using local detail outputs; requires private local inputs.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(arrow)
library(dplyr)
library(lubridate)
library(readr)
library(stringr)

get_latest_processed_eff_date <- function(processed_root = "processed") {
  dirs <- list.dirs(processed_root, recursive = FALSE, full.names = FALSE)
  dirs <- dirs[str_detect(dirs, "^\\d{8}$")]
  if (length(dirs) == 0) stop(sprintf("No processed eff_date folders found under %s", processed_root))
  sort(dirs, decreasing = TRUE)[[1]]
}

rccd_codes <- c("001270-00", "041735-00", "041761-00")
fall_window_start <- ymd("2025-08-01")
fall_window_end <- ymd("2025-12-31")

EFF_DATE <- Sys.getenv("EFF_DATE", unset = NA_character_)
if (is.na(EFF_DATE) || !dir.exists(file.path("processed", EFF_DATE))) {
  EFF_DATE <- get_latest_processed_eff_date()
}

COHORT_YEAR <- as.integer(Sys.getenv("COHORT_YEAR", unset = "2025"))
DETAIL_PARQUET <- Sys.getenv(
  "DETAIL_PARQUET",
  unset = sprintf("full_detail/class_of_%s_nsc_detail.parquet", COHORT_YEAR)
)

out_dir <- Sys.getenv("OUT_DIR", unset = file.path("processed", EFF_DATE))
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

top25_files <- list.files(
  file.path("processed", EFF_DATE),
  pattern = "Top25\\.csv$",
  recursive = TRUE,
  full.names = TRUE
)
top25_files <- top25_files[str_detect(top25_files, "/reports/")]
include_districtwide <- tolower(Sys.getenv("TOP25_INCLUDE_DISTRICTWIDE", unset = "false")) %in% c("1", "true", "t", "yes", "y")
if (!include_districtwide) {
  top25_files <- top25_files[!str_detect(top25_files, "Districtwide_Top25\\.csv$")]
}

top25 <- bind_rows(lapply(top25_files, function(p) {
  district <- basename(dirname(dirname(p)))
  df <- suppressMessages(read_csv(p, col_types = cols(.default = col_character())))
  if (!all(c("Cohort", "College ID", "Count") %in% names(df))) return(NULL)
  df %>%
    mutate(
      District = district,
      Cohort = as.integer(Cohort),
      Count = suppressWarnings(as.integer(Count))
    )
}))

top25_rccd <- top25 %>%
  filter(
    Cohort == COHORT_YEAR,
    `College ID` %in% rccd_codes
  ) %>%
  group_by(District, `College ID`, `College Name`) %>%
  summarise(top25_students = sum(Count, na.rm = TRUE), .groups = "drop")

top25_summary_path <- file.path(out_dir, sprintf("_rccd_top25_cohort%s_by_district.csv", COHORT_YEAR))
write_csv(top25_rccd, top25_summary_path)

message(sprintf("Wrote: %s", top25_summary_path))
message("Note: Top25 reports are truncated to each school's top 25 institutions, so sums are a lower bound (not a complete census).")
print(top25_rccd %>% summarise(top25_students = sum(top25_students), .groups = "drop"))
