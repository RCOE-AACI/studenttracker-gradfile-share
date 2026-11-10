# Synthetic fixtures only. Evaluate the function definition without executing the pipeline.
suppressPackageStartupMessages(library(tidyverse))
root <- getwd()
expressions <- parse("11-Detail.R")
definition <- Filter(function(x) {
  is.call(x) && identical(x[[1]], as.name("<-")) &&
    identical(x[[2]], as.name("load_detail"))
}, as.list(expressions))
stopifnot(length(definition) == 1L)
eval(definition[[1]])

run_test <- function() {
  fixture <- tempfile(pattern = ".synthetic-detail-test-", tmpdir = root)
  dir.create(file.path(fixture, "processed", "20261110"), recursive = TRUE)
  dir.create(file.path(fixture, "data"))
  on.exit({setwd(root); unlink(fixture, recursive = TRUE)}, add = TRUE)
  setwd(fixture)
  write_csv(tibble(Your_Unique_Identifier = "_0000000001", Last_Name = "SYNTHETIC"),
            "processed/20261110/detail.csv")
  write_csv(tibble(SSID = character(), Last_Name = character()),
            "data/nsc_duplicate_corrections.csv")
  stopifnot(nrow(suppressMessages(load_detail("20261110"))) == 1L)
  write_csv(tibble(SSID = "0000000001", Last_Name = "OTHER_SYNTHETIC"),
            "data/nsc_duplicate_corrections.csv")
  stopifnot(nrow(suppressMessages(load_detail("20261110"))) == 1L)
  write_csv(tibble(SSID = "0000000001", Last_Name = "SYNTHETIC"),
            "data/nsc_duplicate_corrections.csv")
  stopifnot(nrow(suppressMessages(load_detail("20261110"))) == 0L)
}
run_test()
cat("Synthetic DETAIL correction tests passed\n")
