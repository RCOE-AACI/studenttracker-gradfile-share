# Historical AVID request workflow. For new requests see 01x-process_avid_request.py and REQ-24.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(stringi)
library(arrow)
library(lubridate)

# Get list of cohort files
county_grad_w_accounts <- readRDS('county_grad_w_accounts.rds')

# Get account reference sheets
ref_sheets <- read_excel("data/account_refs.xlsx")

# Previous AVID
prev_avid <- readRDS('data/AVID_GRADS.rds') %>%
  mutate(
    SchoolCode.x = SchoolCode,
    District = District.x,
    CohortYear = as.character(as.integer(substr(EntryYearinCohort,6,9)) + 3)
  )

# Filter for AVID
avid <- read_csv("data/avid_2024.csv") 


# Make studenttracker compliant student data
service_accounts <- ref_sheets %>%
  group_by(District, SA) %>%
  select(District, SA) %>%
  summarise()

file_suffix <- "_AVID"

county_avid <- county_grad_w_accounts %>% 
  filter(
    SSID %in% avid$SSID,
  ) %>%
  bind_rows(
    prev_avid 
  )


for (i in 1:nrow(service_accounts)) {
  st_gradfile <- county_avid %>%
    filter(
      !is.na(LastName),
      SA == service_accounts[i,] %>% pull(SA)
      ) %>%
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
  print(service_accounts[i,] %>% pull(SA))
  print(service_accounts[i,] %>% pull(District))
  print(
    table(
    substr(st_gradfile$H,1,4)
  )
  )
  cat('\n\n')
  write_delim(
    final_file,
    file = paste0(
      "requestfiles/",
      format(lubridate::today(), format = "%Y%m%d"),
      "_",
      service_accounts[i,] %>% pull(SA),
      "_",
      gsub("\\s","",service_accounts[i, ] %>% pull(District)),
      file_suffix,
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
  county_avid %>%
  group_by(SA, ACT, CDS, District.x, HSName) %>%
  summarise(n = n())
# write_excel_csv(submission_count, "county_cohort_summary.csv")

service_accounts_w_submissions <- ref_sheets %>%
  left_join(submission_count) %>%
  arrange(District, HSName)
# write_excel_csv(service_accounts_w_submissions, "service_account_analysis.csv")

# Python use virtualenv
reticulate::use_virtualenv('r-reticulate')

