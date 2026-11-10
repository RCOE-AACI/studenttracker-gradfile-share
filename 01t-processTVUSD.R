# Historical TVUSD request workflow. Review source years and scope before reuse; also see 01v-process_tvusd_request.py. REQ-07.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(stringi)
library(arrow)
library(lubridate)
library(odbc)

# Get list of cohort files
co2024 <- read_parquet(
  file = 'data/ClassOf24-ClassOf27_152_cohort_outcomes.parquet'
) 
co2023 <- read_parquet(
  file = 'data/2022-2023_152_account.parquet'
) 
co2022 <- read_parquet(
  file = 'data/2021-2022_152_account.parquet'
) 
co2021 <- read_parquet(
  file = 'data/2020-2021_152_account.parquet'
) 
co2020 <- read_parquet(
  file = 'data/2019-2020_152_account.parquet'
) 
countywide <- bind_rows(co2024, co2023, co2022, co2021, co2020) %>% 
  mutate(
    BirthDate = lubridate::as_date(BirthDate, format = "%m/%d/%Y"),
    StudentEnrollmentStartDate =  lubridate::as_date(StudentEnrollmentStartDate,format = "%m/%d/%Y"),
    StudentEnrollmentExitDate = lubridate::as_date(StudentEnrollmentExitDate,format = "%m/%d/%Y")
  ) %>%
  filter(
    StudentEnrollmentExitDate <= '2024-08-31',
    StudentEnrollmentExitDate >= '2019-09-01',
    CohortYear <= '2024'
  ) %>%
  mutate(CDS = paste0(DistrictCode, SchoolCode),
         .before = everything())

# Get IB List
tvusd <- read_excel(
  'data/TVUSD Postsecondary Students 2023.24.xlsx',
  col_types = c("text")
)
st_tvusd <- countywide %>%
  filter(
    SSID %in% tvusd$`Student SSID`
  )

# Get account reference sheets
ref_sheets <- read_excel("data/account_refs.xlsx")

# Load other SINF
sinf_merge <- read_parquet('data/sinf_merge.parquet')

# Submission

county_grad_w_accounts <- st_tvusd %>% 
  left_join(sinf_merge, by = c("SSID", "DistrictCode")) %>%
  left_join(ref_sheets, by = c("CDS"))

missing_names <- county_grad_w_accounts %>%
  filter(is.na(LastName))

duplicated_students <- county_grad_w_accounts %>%
  group_by(SSID) %>%
  filter(n() > 1)

# Make studenttracker compliant student data
service_accounts <- ref_sheets %>%
  group_by(District, SA) %>%
  select(District, SA) %>%
  summarise()

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
      SocioEconomicallyDisadvantaged == "Yes" ~ "Y",
      SocioEconomicallyDisadvantaged == "No" ~ "N",
      TRUE ~ ""
    ), # SED, but inaccurate
    P = "", # 8th Grade Assessment Math
    Q = "", # 8th Grade Assessment ELA/Reading
    R = "", # High School Assessment Result Math
    S = "", # High School Assessment Result ELA/Reading
    T =  case_when(
      EnglishLearner == "Yes" ~ "Y",
      EnglishLearner == "No" ~ "N",
      TRUE ~ ""
    ), # EL indicator [CHRT]
    U = "", # Number math semesters completed
    V = "", # Dual enrollment
    W = case_when(
      StudentswithDisabilities == "Yes" ~ "Y",
      StudentswithDisabilities == "No" ~ "N",
      TRUE ~ ""
    ), # Disability code [CHRT], # Disability
    X = paste(
      if_else(MigrantEd == "Yes", "MIG_Y", "MIG_N"),
      if_else(FosterYouth == "Yes", "FOS_Y", "FOS_N"),
      if_else(Homeless == "Yes", "HOM_Y", "HOM_N"),
      if_else(UC_CSURequirementsMet == "Yes", "AG_Y", "AG_N"),
      if_else(Sealofbiliteracy == "Yes", "SSB_Y", "SSB_N"),
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
      ".txt"
    ),
    col_names=FALSE,
    delim = "\t",
    na = "",
    quote = "none"
  )
  }
}

# Submission counts
submission_count <-
  county_grad_w_accounts %>%
  group_by(SA, ACT, CDS, District.x, HSName) %>%
  summarise(n = n())
# write_excel_csv(submission_count, "county_cohort_summary.csv")

service_accounts_w_submissions <- ref_sheets %>%
  left_join(submission_count) %>%
  arrange(District, HSName)
# write_excel_csv(service_accounts_w_submissions, "service_account_analysis.csv")

# Python use virtualenv
reticulate::use_virtualenv('r-reticulate')
