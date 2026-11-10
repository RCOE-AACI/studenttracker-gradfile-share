# Synthetic configuration checks; no source records are read or written.
source("annual_submission_config.R")
config <- annual_submission_config("2026", "", "20261110")
stopifnot(config$cohort_year == 2026L,
          config$window_start == as.Date("2025-09-01"),
          config$window_end == as.Date("2026-08-31"),
          config$school_year == "2025-2026",
          config$cohort_path == "data/ClassOf26-ClassOf29_152_cohort_outcomes.parquet",
          config$run_date == "20261110",
          identical(config$excluded_districts, c("3367199", "3367231", "3367116")))
stopifnot(annual_submission_config("2025", "data/explicit.parquet", "20261110")$cohort_path == "data/explicit.parquet")
stopifnot(inherits(try(annual_submission_config("bad", "", "20261110"), silent=TRUE), "try-error"))
stopifnot(inherits(try(annual_submission_config("2026", "", "20260230"), silent=TRUE), "try-error"))
# Exercise the actual annual input transformation with synthetic rows and a fake
# parquet reader. This checks that the configured path/window/exclusions reach the pipeline.
suppressPackageStartupMessages(library(tidyverse))
rows <- tibble(DistrictCode = c(config$excluded_districts, "0000000", "0000000"),
               SchoolCode = "0000001", BirthDate = "01/01/2008",
               StudentEnrollmentStartDate = "09/01/2025",
               StudentEnrollmentExitDate = c(rep("06/01/2026", 4), "06/01/2025"),
               DSEA = "0000000")
environment <- new.env(parent = globalenv())
environment$project <- config
environment$read_parquet <- function(file) {
  stopifnot(identical(file, config$cohort_path))
  rows
}
expressions <- Filter(function(x) is.call(x) && identical(x[[1]], as.name("<-")) &&
                        identical(x[[2]], as.name("countywide")),
                      as.list(parse("01-process.R")))
stopifnot(length(expressions) == 1L)
eval(expressions[[1]], envir = environment)
stopifnot(nrow(environment$countywide) == 1L,
          environment$countywide$DistrictCode == "0000000",
          environment$countywide$StudentEnrollmentExitDate == as.Date("2026-06-01"))
guard_environment <- new.env(parent = globalenv())
guard_environment$dir <- function(...) "CHRT.synthetic.csv"
script <- as.list(parse("01-process.R"))
input_listing <- Filter(function(x) is.call(x) && identical(x[[1]], as.name("<-")) &&
                         identical(x[[2]], as.name("chrt_files")), script)
guard <- Filter(function(x) is.call(x) && identical(x[[1]], as.name("if")) &&
                  "chrt_files" %in% all.names(x), script)
stopifnot(length(input_listing) == 1L, length(guard) == 1L)
eval(input_listing[[1]], envir = guard_environment)
failure <- try(eval(guard[[1]], envir = guard_environment), silent = TRUE)
stopifnot(inherits(failure, "try-error"), grepl("REQ-18", as.character(failure)))
cat("Annual submission configuration tests passed\n")
