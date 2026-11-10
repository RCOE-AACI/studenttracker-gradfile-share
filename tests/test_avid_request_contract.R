# Synthetic test fixtures only; values here are invented and are not student records.
suppressPackageStartupMessages(source("01x-process_avid_request.R"))

window <- report_window("2024-2025", 2025L)
stopifnot(identical(window$start, as.Date("2024-09-01")))
stopifnot(identical(window$end, as.Date("2025-08-31")))

sample <- tibble::tibble(
  FirstName = "Jose.",
  MiddleName = "A",
  LastName = "Nunez",
  Suffix = "",
  BirthDate = as.Date("2006-01-02"),
  StudentEnrollmentExitDate = as.Date("2025-06-10"),
  ACT = "050001",
  SSID = "1234567890",
  Gender = "M",
  EthnicityRace = "Hispanic",
  SocioEconomicallyDisadvantaged = "Yes",
  EnglishLearner = "No",
  StudentswithDisabilities = "No",
  MigrantEd = "No",
  FosterYouth = "No",
  Homeless = "No",
  UC_CSURequirementsMet = "Yes",
  Sealofbiliteracy = "No"
)

body <- build_request_body(sample)
stopifnot(ncol(body) == 25L)
stopifnot(body$A[[1]] == "D3")
stopifnot(body$G[[1]] == "20060102")
stopifnot(body$H[[1]] == "20250610")
stopifnot(body$L[[1]] == "1234567890")
stopifnot(!startsWith(body$L[[1]], "_"))
stopifnot(body$V[[1]] == "")
stopifnot(sanitize_text("Na") == "Na")
stopifnot(sanitize_optional_name("Na") == "Na")
stopifnot(normalize_account_code("55457", 6L) == "055457")
stopifnot(normalize_account_code("A30452", 6L) == "A30452")

missing_variants <- dplyr::bind_rows(
  dplyr::mutate(sample, MiddleName = NA_character_, Suffix = "NA"),
  dplyr::mutate(sample, MiddleName = " Null ", Suffix = NA_character_),
  dplyr::mutate(sample, MiddleName = "N/A", Suffix = "None")
)
missing_body <- build_request_body(missing_variants)
stopifnot(all(missing_body$D == ""))
stopifnot(all(missing_body$F == ""))

path <- tempfile(fileext = ".txt")
body_with_na <- body
body_with_na$D[[1]] <- NA_character_
write_lines_atomic(path, request_lines("10000000", "TEST DISTRICT", "20260824", body_with_na))
validate_request_file(path, "10000000", 1L, "20260824")
unlink(path)

bad_path <- tempfile(fileext = ".txt")
bad_body <- body
bad_body$D[[1]] <- "Null"
write_lines_atomic(bad_path, request_lines("10000000", "TEST DISTRICT", "20260824", bad_body))
bad_result <- try(validate_request_file(bad_path, "10000000", 1L, "20260824"), silent = TRUE)
stopifnot(inherits(bad_result, "try-error"))
unlink(bad_path)

cat("AVID request contract tests passed\n")
