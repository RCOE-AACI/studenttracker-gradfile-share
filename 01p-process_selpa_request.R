# SELPA request: source-list membership bounds the cohort; missing required fields go to blockers. REQ-05 through REQ-07.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(arrow)

WRITE_WITH_BLOCKERS <- TRUE

normalize_token <- function(x) {
  x %>%
    tidyr::replace_na("") %>%
    toupper() %>%
    gsub("[^A-Z0-9]", "", .)
}

normalize_selpa_school <- function(x) {
  x %>%
    tidyr::replace_na("") %>%
    toupper() %>%
    gsub("^[^-]+ - ", "", .) %>%
    gsub("[^A-Z0-9]", "", .) %>%
    gsub("SENIOR", "", .) %>%
    gsub("SCHOOL", "", .) %>%
    gsub("HIGH$", "HIGHSCHOOL", .)
}

district_alias <- c(
  "ALVORDUNIFIED" = "ALVORDUNIFIEDSCHOOLDISTRICT",
  "BANNINGUNIFIED" = "BANNINGUNIFIEDSCHOOLDISTRICT",
  "BEAUMONTUNIFIED" = "BEAUMONTUNIFIEDSCHOOLDISTRICT",
  "COACHELLAVALLEYUNIFIED" = "COACHELLAVALLEYUNIFIEDSCHOOLDISTRICT",
  "DESERTSANDSUNIFIED" = "DESERTSANDSUNIFIEDSCHOOLDISTRICT",
  "HEMETUNIFIED" = "HEMETUNIFIEDSCHOOLDISTRICT",
  "JURUPAUNIFIED" = "JURUPAUNIFIEDSCHOOLDISTRICT",
  "LAKEELSINOREUNIFIED" = "LAKEELSINOREUNIFIEDSCHOOLDISTRICT",
  "MURRIETAVALLEYUNIFIED" = "MURRIETAVALLEYUNIFIEDSCHOOLDISTRICT",
  "NUVIEWUNIONELEMENTARY" = "NUVIEWUNIONSCHOOLDISTRICT",
  "PALMSPRINGSUNIFIED" = "PALMSPRINGSUNIFIEDSCHOOLDISTRICT",
  "PALOVERDEUNIFIED" = "PALOVERDEUNIFIEDSCHOOLDISTRICT",
  "PERRISUNIONHIGH" = "PERRISUNIONHIGHSCHOOLDISTRICT",
  "RCOEALTERNATIVEEDUCATION" = "RIVERSIDECOUNTYOFFICEOFEDUCATION",
  "RCOERIVERSIDECOUNTYOFFICEOFEDUCATION" = "RIVERSIDECOUNTYOFFICEOFEDUCATION",
  "SANJACINTOUNIFIED" = "SANJACINTOUNIFIEDSCHOOLDISTRICT",
  "SANJACINTOVALLEYACADEMY" = "SANJACINTOVALLEYACADEMY",
  "SANTAROSAACADEMYCHARTERSCHOOL" = "SANTAROSAACADEMY",
  "SCALELEADERSHIPACADEMYEAST" = "LEADERSHIPMILITARYACADEMY",
  "VALVERDEUNIFIED" = "VALVERDEUNIFIEDSCHOOLDISTRICT"
)

map_district_alias <- function(x) {
  dplyr::recode(
    normalize_token(x),
    !!!district_alias,
    .default = normalize_token(x)
  )
}

selpa <- readr::read_csv(
  "data/SELPA25/SEIS - Post Secondary List 04.14.26 - EOY 2026.csv",
  show_col_types = FALSE
) %>%
  transmute(
    SEIS_ID = as.character(`SEIS ID`),
    SSID = as.character(SSID),
    LastName = `Last Name`,
    FirstName = `First Name`,
    BirthDate = lubridate::mdy(`Date of Birth`),
    DistrictOfService = `District of Service (Reporting LEA)`,
    SchoolOfAttendance = `School of Attendance`,
    GradeCode = as.character(`Grade Code`),
    LastAttendanceDate = lubridate::mdy(`Date of Exit from SpEd`),
    ExitReason = as.character(`Exit Reason`),
    PostsecondaryStatus = `Postsecondary Status`
  ) %>%
  distinct() %>%
  mutate(
    district_norm = map_district_alias(DistrictOfService),
    school_norm = normalize_selpa_school(SchoolOfAttendance)
  )

cohort_files <- dir("data/", pattern = "*152_account.parquet", full.names = TRUE)
cohort <- bind_rows(lapply(cohort_files, function(path) {
  curr <- read_parquet(path)
  tibble(
    SSID = as.character(curr$SSID),
    DistrictCode = as.character(curr$DistrictCode),
    SchoolCode = as.character(curr$SchoolCode),
    StudentEnrollmentExitDate = lubridate::as_date(curr$StudentEnrollmentExitDate, format = "%m/%d/%Y"),
    Gender = as.character(curr$Gender),
    EthnicityRace = as.character(curr$EthnicityRace),
    SocioEconomicallyDisadvantaged = as.character(curr$SocioEconomicallyDisadvantaged),
    EnglishLearner = as.character(curr$EnglishLearner),
    StudentswithDisabilities = as.character(curr$StudentswithDisabilities),
    FosterYouth = as.character(curr$FosterYouth),
    Homeless = as.character(curr$Homeless),
    Sealofbiliteracy = as.character(curr$Sealofbiliteracy),
    UC_CSURequirementsMet = as.character(curr$UC_CSURequirementsMet)
  )
})) %>%
  distinct()

refs <- read_excel("data/account_refs.xlsx") %>%
  mutate(
    district_norm = normalize_token(District),
    school_norm = normalize_selpa_school(HSName)
  )

selpa_enriched <- selpa %>%
  left_join(cohort, by = "SSID") %>%
  mutate(CDS = paste0(DistrictCode, SchoolCode)) %>%
  left_join(
    refs %>% select(CDS, District, SA, ACT, HSName),
    by = "CDS"
  ) %>%
  rename(
    District_ref = District,
    SA_ref = SA,
    ACT_ref = ACT,
    HSName_ref = HSName
  ) %>%
  left_join(
    refs %>% select(district_norm, school_norm, District, SA, ACT, HSName),
    by = c("district_norm", "school_norm"),
    suffix = c("", "_name")
  ) %>%
  mutate(
    District = coalesce(District_ref, District),
    SA = coalesce(SA_ref, SA),
    ACT = coalesce(ACT_ref, ACT),
    HSName = coalesce(HSName_ref, HSName),
    LastAttendanceDate = coalesce(StudentEnrollmentExitDate, LastAttendanceDate)
  )

blockers <- selpa_enriched %>%
  mutate(
    blocker_reason = case_when(
      is.na(FirstName) | FirstName == "" ~ "Missing first name",
      is.na(LastName) | LastName == "" ~ "Missing last name",
      is.na(BirthDate) ~ "Missing date of birth",
      is.na(LastAttendanceDate) ~ "Missing last date of attendance",
      is.na(SA) ~ "Missing account code and account name",
      is.na(ACT) ~ "Missing ACT code",
      TRUE ~ NA_character_
    )
  ) %>%
  filter(!is.na(blocker_reason)) %>%
  select(
    SSID,
    SEIS_ID,
    DistrictOfService,
    SchoolOfAttendance,
    blocker_reason
  ) %>%
  distinct()

readr::write_excel_csv(blockers, "selpa_request_blockers.csv")

if (nrow(blockers) > 0 && !WRITE_WITH_BLOCKERS) {
  stop(sprintf("SELPA request blocked: %s students are missing required request fields.", nrow(blockers)))
}

selpa_request_ready <- selpa_enriched %>%
  anti_join(blockers, by = c("SSID", "SEIS_ID", "DistrictOfService", "SchoolOfAttendance"))

service_accounts <- selpa_request_ready %>%
  filter(!is.na(SA)) %>%
  distinct(District, SA) %>%
  arrange(District, SA)

for (i in 1:nrow(service_accounts)) {
  st_gradfile <- selpa_request_ready %>%
    filter(
      SA == service_accounts[i, ] %>% pull(SA)
    ) %>%
    transmute(
      A = "D3",
      B = "",
      C = FirstName,
      D = "",
      E = LastName,
      F = "",
      G = format(BirthDate, format = "%Y%m%d"),
      H = format(LastAttendanceDate, format = "%Y%m%d"),
      I = ACT,
      J = "",
      K = SEIS_ID,
      L = SSID,
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
        "SELPA",
        paste0("GRADE_", GradeCode),
        paste0("EXIT_", ExitReason),
        sep = "."
      ),
      Y = "ED"
    )

  if (nrow(st_gradfile) > 0) {
    header <- tibble(
      A = "H3",
      B = service_accounts[i, ] %>% pull(SA),
      C = "",
      D = service_accounts[i, ] %>% pull(District),
      E = format(lubridate::today(), format = "%Y%m%d"),
      F = "SE",
      G = "D"
    )

    trailer <- tibble(
      A = "T3",
      B = as.character(nrow(st_gradfile) + 2)
    )

    final_file <- bind_rows(
      header,
      st_gradfile,
      trailer
    )

    readr::write_delim(
      final_file,
      file = paste0(
        "requestfiles/",
        format(lubridate::today(), format = "%Y%m%d"),
        "_",
        service_accounts[i, ] %>% pull(SA),
        "_",
        gsub("\\s", "", service_accounts[i, ] %>% pull(District)),
        "_SELPA.txt"
      ),
      col_names = FALSE,
      delim = "\t",
      na = "",
      quote = "none"
    )

    readr::write_delim(
      bind_rows(
        header,
        st_gradfile %>% slice_sample(n = min(nrow(st_gradfile), 800)),
        trailer %>% mutate(B = as.character(min(nrow(st_gradfile), 800) + 2))
      ),
      file = paste0(
        "requestfiles/test_file/",
        service_accounts[i, ] %>% pull(SA),
        "_",
        gsub("\\s", "", service_accounts[i, ] %>% pull(District)),
        "_SELPA.txt"
      ),
      col_names = FALSE,
      delim = "\t",
      na = "",
      quote = "none"
    )
  }
}

selpa_request_summary <- selpa_request_ready %>%
  filter(!is.na(SA), !is.na(ACT)) %>%
  count(SA, ACT, District, HSName, name = "n") %>%
  arrange(desc(n))

readr::write_excel_csv(selpa_request_summary, "selpa_request_summary.csv")
