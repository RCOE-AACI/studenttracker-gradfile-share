# MVUSD CTE request: intersect the supplied IDs with the configured district and class before account enrichment. REQ-07.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(arrow)
library(lubridate)

mvusd_district_code <- "3375200"
mvusd_service_account <- "90000002"
mvusd_district_name <- "MURRIETA VALLEY UNIFIED SCHOOL DISTRICT"
program_suffix <- "CTE"
run_date <- format(lubridate::today(), "%Y%m%d")

input_path <- "data/MVUSD/CTE_SSID_MurrietaValleyUSD_ClassOf2025.csv"
cohort_path <- "data/ClassOf25-ClassOf28_152_cohort_outcomes.parquet"
sinf_path <- "data/sinf_merge.parquet"
account_ref_path <- "data/account_refs.xlsx"

request_dir <- "requestfiles"
test_dir <- file.path(request_dir, "test_file")

main_output_path <- file.path(
  request_dir,
  paste0(
    run_date,
    "_",
    mvusd_service_account,
    "_",
    gsub("\\s", "", mvusd_district_name),
    "_",
    program_suffix,
    ".txt"
  )
)
test_output_path <- file.path(
  test_dir,
  paste0(
    mvusd_service_account,
    "_",
    gsub("\\s", "", mvusd_district_name),
    "_",
    program_suffix,
    ".txt"
  )
)
unmatched_output_path <- file.path(
  request_dir,
  paste0(
    run_date,
    "_",
    mvusd_service_account,
    "_",
    gsub("\\s", "", mvusd_district_name),
    "_",
    program_suffix,
    "_unmatched.csv"
  )
)

dir.create(request_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(test_dir, recursive = TRUE, showWarnings = FALSE)

mvusd_ssids <- read_csv(
  input_path,
  col_types = cols(SSID = col_character()),
  show_col_types = FALSE
) %>%
  transmute(SSID = trimws(SSID)) %>%
  filter(!is.na(SSID), SSID != "") %>%
  distinct()

countywide <- read_parquet(cohort_path) %>%
  mutate(
    SSID = as.character(SSID),
    BirthDate = lubridate::as_date(BirthDate, format = "%m/%d/%Y"),
    StudentEnrollmentStartDate = lubridate::as_date(
      StudentEnrollmentStartDate,
      format = "%m/%d/%Y"
    ),
    StudentEnrollmentExitDate = lubridate::as_date(
      StudentEnrollmentExitDate,
      format = "%m/%d/%Y"
    ),
    CohortYear = as.integer(CohortYear),
    CDS = paste0(DistrictCode, SchoolCode)
  ) %>%
  filter(
    DistrictCode == mvusd_district_code,
    CohortYear == 2025L
  )

matched_students <- countywide %>%
  filter(SSID %in% mvusd_ssids$SSID)

unmatched_ssids <- mvusd_ssids %>%
  anti_join(matched_students %>% distinct(SSID), by = "SSID") %>%
  mutate(reason = "SSID not found in MVUSD Class of 2025 cohort parquet")

ref_sheets <- read_excel(account_ref_path) %>%
  mutate(
    SA = as.character(SA),
    ACT = as.character(ACT),
    CDS = as.character(CDS)
  ) %>%
  filter(
    SA == mvusd_service_account,
    District == mvusd_district_name
  )

sinf_merge <- read_parquet(sinf_path) %>%
  mutate(
    SSID = as.character(SSID),
    DistrictCode = as.character(DistrictCode)
  )

county_grad_w_accounts <- matched_students %>%
  left_join(sinf_merge, by = c("SSID", "DistrictCode")) %>%
  left_join(ref_sheets, by = "CDS") %>%
  filter(!is.na(LastName), !is.na(ACT), SA == mvusd_service_account)

st_gradfile <- county_grad_w_accounts %>%
  transmute(
    A = "D3",
    B = "",
    C = FirstName,
    D = MiddleName,
    E = LastName,
    F = Suffix,
    G = format(BirthDate, format = "%Y%m%d"),
    H = format(StudentEnrollmentExitDate, format = "%Y%m%d"),
    I = ACT,
    J = "",
    K = "",
    L = as.character(SSID),
    M = if_else(Gender %in% c("M", "F"), Gender, ""),
    N = case_when(
      EthnicityRace == "African American" ~ "BL",
      EthnicityRace == "Asian" ~ "AS",
      EthnicityRace == "Filipino" ~ "AS",
      EthnicityRace == "Native American" ~ "AM",
      EthnicityRace == "Pacific Islander" ~ "PI",
      EthnicityRace == "Two or More" ~ "MU",
      EthnicityRace == "White" ~ "WH",
      EthnicityRace == "Hispanic" ~ "HI",
      TRUE ~ ""
    ),
    O = case_when(
      SocioEconomicallyDisadvantaged == "Yes" ~ "Y",
      SocioEconomicallyDisadvantaged == "No" ~ "N",
      TRUE ~ ""
    ),
    P = "",
    Q = "",
    R = "",
    S = "",
    T = case_when(
      EnglishLearner == "Yes" ~ "Y",
      EnglishLearner == "No" ~ "N",
      TRUE ~ ""
    ),
    U = "",
    V = "",
    W = case_when(
      StudentswithDisabilities == "Yes" ~ "Y",
      StudentswithDisabilities == "No" ~ "N",
      TRUE ~ ""
    ),
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

header <- tibble(
  A = "H3",
  B = mvusd_service_account,
  C = "",
  D = mvusd_district_name,
  E = run_date,
  F = "SE",
  G = "D"
)

trailer <- tibble(
  A = "T3",
  B = as.character(nrow(st_gradfile) + 2)
)

if (nrow(st_gradfile) == 0) {
  stop("No matched MVUSD students were available to write a request file.")
}

write_delim(
  bind_rows(header, st_gradfile, trailer),
  file = main_output_path,
  col_names = FALSE,
  delim = "\t",
  na = "",
  quote = "none"
)

write_delim(
  bind_rows(
    header,
    st_gradfile %>% slice_sample(n = min(nrow(st_gradfile), 800)),
    trailer %>% mutate(B = as.character(min(nrow(st_gradfile), 800) + 2))
  ),
  file = test_output_path,
  col_names = FALSE,
  delim = "\t",
  na = "",
  quote = "none"
)

write_excel_csv(unmatched_ssids, unmatched_output_path)

school_summary <- county_grad_w_accounts %>%
  count(ACT, CDS, HSName, sort = TRUE)

cat("MVUSD CTE request file summary\n")
cat("Input SSIDs:", nrow(mvusd_ssids), "\n")
cat("Matched students:", nrow(st_gradfile), "\n")
cat("Unmatched SSIDs:", nrow(unmatched_ssids), "\n")
cat("Main file:", main_output_path, "\n")
cat("Test file:", test_output_path, "\n")
cat("Unmatched file:", unmatched_output_path, "\n\n")
print(school_summary)
