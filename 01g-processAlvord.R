# Alvord AVID/IB/PUENTE request workflow: combine class-specific lists, restrict CDS to Alvord, then emit one request per program. REQ-08.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(stringi)
library(arrow)
library(lubridate)
library(odbc)

# Get list of cohort files
read_cohort <- function(path) {
  read_parquet(path) %>%
    mutate(DSEA = as.character(DSEA))
}

co2024 <- read_cohort(
  'data/ClassOf24-ClassOf27_152_cohort_outcomes.parquet'
)
co2025 <- read_cohort(
  'data/ClassOf25-ClassOf28_152_cohort_outcomes.parquet'
)
co2023 <- read_cohort(
  'data/2022-2023_152_account.parquet'
)
co2022 <- read_cohort(
  'data/2021-2022_152_account.parquet'
)
co2021 <- read_cohort(
  'data/2020-2021_152_account.parquet'
)
co2020 <- read_cohort(
  'data/2019-2020_152_account.parquet'
)
countywide <- bind_rows(co2025, co2024, co2023, co2022, co2021, co2020) %>% 
  mutate(
    BirthDate = lubridate::as_date(BirthDate, format = "%m/%d/%Y"),
    StudentEnrollmentStartDate =  lubridate::as_date(StudentEnrollmentStartDate,format = "%m/%d/%Y"),
    StudentEnrollmentExitDate = lubridate::as_date(StudentEnrollmentExitDate,format = "%m/%d/%Y"),
    CohortYear = as.integer(CohortYear)
  ) %>%
  filter(
    StudentEnrollmentExitDate <= '2025-08-31',
    StudentEnrollmentExitDate >= '2019-09-01',
    CohortYear <= '2025'
  ) %>%
  mutate(CDS = paste0(DistrictCode, SchoolCode),
         .before = everything())

alvord_district_code <- "3366977"

read_alvord_list <- function(path, ssid_col = "State Student ID") {
  read_excel(path) %>%
    transmute(
      SSID = as.character(.data[[ssid_col]])
    ) %>%
    filter(!is.na(SSID), SSID != "") %>%
    distinct()
}

read_alvord_csv_list <- function(path, ssid_col = "SSID") {
  read_csv(path, show_col_types = FALSE) %>%
    transmute(
      SSID = as.character(.data[[ssid_col]])
    ) %>%
    filter(!is.na(SSID), SSID != "") %>%
    distinct()
}

# Get 2024-25 lists (apply to Class of 2025)
alv_avid_2425 <- read_alvord_list(
  'data/alvord/2025/AVID Graduates 2024-25.xlsx'
)
alv_ib_2425 <- read_alvord_list(
  'data/alvord/2025/IB Graduates 2024-25.xlsx'
)
alv_puente_2425 <- read_alvord_list(
  'data/alvord/2025/Puente students 2024-25.xlsx'
)

# Get 2023-24 lists (apply to Class of 2024)
avid_2324_path <- "data/avid_2024.csv"
alv_avid_2324 <- if (file.exists(avid_2324_path)) {
  read_alvord_csv_list(avid_2324_path, ssid_col = "SSID")
} else {
  tibble(SSID = character())
}
alv_ib_2324 <- read_alvord_list(
  'data/alvord/IB Student Tracker.xlsx',
  ssid_col = "State Student ID"
)
alv_puente_2324 <- read_alvord_list(
  'data/alvord/Puente Student Tracker.xlsx',
  ssid_col = "SSID"
)


# Get account reference sheets
ref_sheets <- read_excel("data/account_refs.xlsx")

# Load other SINF
sinf_merge <- read_parquet('data/sinf_merge.parquet')

# Make studenttracker compliant student data
service_accounts <- ref_sheets %>%
  group_by(District, SA) %>%
  select(District, SA) %>%
  summarise()

group_lists <- list(
  list(
    name = "AVID",
    cohort_sets = list(
      list(cohort = 2025, ssids = alv_avid_2425$SSID),
      list(cohort = 2024, ssids = alv_avid_2324$SSID)
    )
  ),
  list(
    name = "IB",
    cohort_sets = list(
      list(cohort = 2025, ssids = alv_ib_2425$SSID),
      list(cohort = 2024, ssids = alv_ib_2324$SSID)
    )
  ),
  list(
    name = "PUENTE",
    cohort_sets = list(
      list(cohort = 2025, ssids = alv_puente_2425$SSID),
      list(cohort = 2024, ssids = alv_puente_2324$SSID)
    )
  )
)

missing_names <- list()
duplicated_students <- list()
group_summary <- tibble()

for (group_info in group_lists) {
  group_name <- group_info$name
  group_key <- group_name

  # Submission
  cohort_sets <- lapply(group_info$cohort_sets, function(x) {
    countywide %>%
      filter(CohortYear == x$cohort) %>%
      filter(SSID %in% x$ssids) %>%
      filter(substr(CDS, 1, 7) == alvord_district_code)
  })
  group_cohort <- bind_rows(cohort_sets) %>%
    distinct()

  cohort_counts <- tibble(CohortYear = c(2024L, 2025L)) %>%
    left_join(
      group_cohort %>% count(CohortYear, name = "n"),
      by = "CohortYear"
    ) %>%
    mutate(
      n = replace_na(n, 0L),
      Group = group_name
    )
  group_summary <- bind_rows(group_summary, cohort_counts)

  county_grad_w_accounts <- group_cohort %>% 
    left_join(sinf_merge, by = c("SSID", "DistrictCode")) %>%
    left_join(ref_sheets, by = c("CDS"))

  missing_names[[group_key]] <- county_grad_w_accounts %>%
    filter(is.na(LastName))

  duplicated_students[[group_key]] <- county_grad_w_accounts %>%
    group_by(SSID) %>%
    filter(n() > 1)

  for (i in 1:nrow(service_accounts)) {
    st_gradfile <- county_grad_w_accounts %>%
      filter(SA == service_accounts[i,] %>% pull(SA)) %>%
    transmute(
      A = "D3", # PD3
      B = "", # SSN
      C = FirstName,
      D = MiddleName,
      E = LastName, 
      F = Suffix, 
      G = format(BirthDate, format = "%Y%m%d"),
      H = format(StudentEnrollmentExitDate, format = "%Y%m%d"), 
      I = ACT, # ACT Code  [RefSheet]
      J = "",
      K = "",
      L = as.character(SSID), 
      M = if_else(Gender %in% c("M", "F"),Gender,""), # Gender [CHRT],  
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
      ), # Race, but CENR is not accurate
      O = case_when(
        substr(SocioEconomicallyDisadvantaged,1,1) == "Y" ~ "Y",
        substr(SocioEconomicallyDisadvantaged,1,1) == "N" ~ "N",
        TRUE ~ ""
      ), # SED, but inaccurate
      P = "", # 8th Grade Assessment Math
      Q = "", # 8th Grade Assessment ELA/Reading
      R = "", # High School Assessment Result Math
      S = "", # High School Assessment Result ELA/Reading
      T =  case_when(
        substr(EnglishLearner,1,1) == "Y" ~ "Y",
        substr(EnglishLearner,1,1) == "N" ~ "N",
        TRUE ~ ""
      ), # EL indicator [CHRT]
      U = "", # Number math semesters completed
      V = "", # Dual enrollment
      W = case_when(
        substr(StudentswithDisabilities,1,1) == "Y" ~ "Y",
        substr(StudentswithDisabilities,1,1) == "N" ~ "N",
        TRUE ~ ""
      ), # Disability code [CHRT], # Disability
      X = paste(
        if_else(substr(MigrantEd,1,1) == "Y", "MIG_Y", "MIG_N"),
        if_else(substr(FosterYouth,1,1) == "Y", "FOS_Y", "FOS_N"),
        if_else(substr(Homeless,1,1) == "Y", "HOM_Y", "HOM_N"),
        if_else(substr(UC_CSURequirementsMet,1,1) == "Y", "AG_Y", "AG_N"),
        if_else(substr(Sealofbiliteracy,1,1) == "Y", "SSB_Y", "SSB_N"),
        sep= "."
      ), #Program Code [CHRT], # Program code
      Y = "ED" 
    )
    header <- tibble(
      A="H3",
      B=service_accounts[i,] %>% pull(SA),
      C="",
      D=service_accounts[i,] %>% pull(District),
      E=format(lubridate::today(),format = "%Y%m%d"),
      F="SE",
      G="D"
    ) 
    trailer <- tibble(
      A = "T3",
      B = as.character((nrow(st_gradfile) + 2))
    )
    if (nrow(st_gradfile) > 0 ){
      final_file <- bind_rows(
      header,
      st_gradfile,
      trailer
    )
    write_delim(
      final_file,
      file = paste0(
        "requestfiles/",
        format(lubridate::today(), format = "%Y%m%d"),
        "_",
        service_accounts[i,] %>% pull(SA),
        "_",
        gsub("\\s","",service_accounts[i, ] %>% pull(District)),
        "_",
        group_name,
        ".txt"
      ),
      col_names=FALSE,
      delim = "\t",
      na = "",
      quote = "none"
    )
    write_delim(
      bind_rows(header, 
                st_gradfile %>% slice_sample(n = min(nrow(st_gradfile),800)),
                trailer %>% mutate(B = as.character(min(nrow(st_gradfile), 800) + 2))
                ),
      file = paste0(
        "requestfiles/test_file/",
        service_accounts[i,] %>% pull(SA),
        "_",
        gsub("\\s","",service_accounts[i, ] %>% pull(District)),
        "_",
        group_name,
        ".txt"
      ),
      col_names=FALSE,
      delim = "\t",
      na = "",
      quote = "none"
    )
    }
  }
}

group_summary <- group_summary %>%
  arrange(Group, CohortYear)
print(group_summary)

# Python use virtualenv
reticulate::use_virtualenv('r-reticulate')
