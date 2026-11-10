# Ingest RCCD term inputs into a common local schema before consolidation. REQ-16, DEC-04.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(arrow)
library(dplyr)
library(purrr)
library(readr)
library(stringr)

rccd_list_terms <- function(rccd_root = "data/RCCD") {
  term_dirs <- list.dirs(rccd_root, full.names = TRUE, recursive = FALSE)
  term_dirs <- term_dirs[basename(term_dirs) != ""]
  term_dirs <- term_dirs[!str_starts(basename(term_dirs), fixed("."))]
  term_dirs
}

rccd_read_term <- function(term_dir, term_code = basename(term_dir)) {
  parquet_files <- list.files(term_dir, pattern = "\\.parquet$", full.names = TRUE)
  csv_files <- list.files(term_dir, pattern = "\\.csv$", full.names = TRUE)
  csv_files <- csv_files[!str_detect(basename(csv_files), "^\\.")]

  if (length(parquet_files) > 0) {
    rccd <- read_parquet(parquet_files[[1]])
    rccd <- rccd %>% mutate(across(everything(), as.character))
  } else if (length(csv_files) > 0) {
    rccd <- purrr::map_dfr(
      csv_files,
      ~ read_csv(.x, col_types = cols(.default = col_character()))
    )
  } else {
    stop(sprintf("No RCCD files found in %s", term_dir))
  }

  if (!("Academic Term" %in% names(rccd))) {
    rccd <- rccd %>% mutate(`Academic Term` = term_code)
  }

  rccd
}

rccd_standardize <- function(rccd_tbl) {
  required_cols <- c(
    "Academic Term",
    "College Student ID",
    "First Name",
    "Last Name",
    "Date of Birth",
    "School Code",
    "Branch Code",
    "Term Begin Date",
    "Term End Date"
  )
  missing_cols <- setdiff(required_cols, names(rccd_tbl))
  if (length(missing_cols) > 0) {
    stop(sprintf("RCCD missing required columns: %s", paste(missing_cols, collapse = ", ")))
  }

  rccd_tbl %>%
    mutate(
      `College_Code/Branch` = paste0(.data[["School Code"]], "-", .data[["Branch Code"]])
    )
}

rccd_read_all_terms <- function(rccd_root = "data/RCCD") {
  term_dirs <- rccd_list_terms(rccd_root)
  if (length(term_dirs) == 0) stop(sprintf("No term folders found under %s", rccd_root))

  purrr::map_dfr(
    term_dirs,
    ~ rccd_standardize(rccd_read_term(.x, basename(.x)))
  )
}
