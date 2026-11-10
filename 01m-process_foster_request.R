# Foster cohort request: select the program cohort, enrich names/accounts, then write request and audit outputs. REQ-05, REQ-06, REQ-24.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(readxl)
library(stringi)
library(arrow)

# Settings
PROCESS_SINF <- FALSE


# Get list of cohort files
county_cohort <- tibble()
countywide <- tibble()
files = dir('data/', pattern = "*152_account.parquet")
for (i in files) {
  curr_chrt <- read_parquet(
    paste0("data/", i),
  ) %>%
    mutate(
      DSEA = as.character(DSEA)
    )
  countywide <- countywide %>% bind_rows(curr_chrt)
}
county_cohort <- countywide %>%
  mutate(
    BirthDate = lubridate::as_date(BirthDate, format = "%m/%d/%Y"),
    StudentEnrollmentStartDate =  lubridate::as_date(StudentEnrollmentStartDate,format = "%m/%d/%Y"),
    StudentEnrollmentExitDate = lubridate::as_date(StudentEnrollmentExitDate,format = "%m/%d/%Y"),
    ) %>%
  mutate(CDS = paste0(DistrictCode, SchoolCode),
         .before = everything()) %>%
  distinct()

# Get account reference sheets
ref_sheets <- read_excel("data/account_refs.xlsx")

# Do county wide data
county_grad <- county_cohort %>% filter(CohortCategory == "HSDiplomaGraduate", FosterYouth == "Yes")

# Name function
sanitize_names <- function(names) {
  new_names <- names %>%
    stri_trans_general(., "latin-ascii") %>% 
    gsub("\\.", "", .)
  return(new_names)
}

if (PROCESS_SINF) {

  # Read in SINF
  all_sinf <- tibble()
  files <- dir('data/SINF')
  for (i in files) {
    dist_sinf <- read_delim(
      paste0('data/SINF/', i), 
      delim = "^",
      col_names = FALSE,
      col_types = cols(
        .default = col_character()  
      )
      )
    all_sinf <- bind_rows(all_sinf, dist_sinf)
  }
  
  sinf_headers <- read_excel(
    'CALPADScfsforms.xlsx',
    sheet = 'Student Information',
    skip = 1
  )
  
  sinf_final <- all_sinf %>%
    distinct()
  names(sinf_final) <- c(sinf_headers %>% pull("Public Name"), 'Upload Date', 'Last Date Updated')
  write_parquet(sinf_final, 'data/cumulative_sinf.parquet')
  
  sinf_merge <- all_sinf %>%
    transmute(
      SSID = X9,
      LastName = sanitize_names(X13),
      FirstName = sanitize_names(X11),
      MiddleName = sanitize_names(X12),
      Suffix = sanitize_names(X14),
      PrevLast = sanitize_names(X16),
      PrevFirst = sanitize_names(X15),
      DistrictCode = X6,
      SchoolCode = X7,
      ModifyDate = X51
    ) %>%
    group_by(DistrictCode, SSID) %>%
    arrange(desc(ModifyDate)) %>%
    filter(row_number() == 1) %>%
    ungroup() %>%
    distinct()
  
  write_parquet(sinf_merge, 'data/sinf_merge.parquet')

} else
{
  sinf_merge <- read_parquet('data/sinf_merge.parquet')
}

county_grad_w_accounts <- county_grad %>% 
  left_join(sinf_merge, by = c("SSID", "DistrictCode")) %>%
  mutate(
    CDS = if_else(CDS == '01252370125237', '33103300125237', CDS)
  ) %>%
  left_join(ref_sheets) %>%
  filter(!is.na(LastName))

# saveRDS(county_grad_w_accounts, "county_grad_w_accounts.rds")

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
      L = SSID, 
      M = if_else(Gender %in% c("M", "F"),Gender,""), 
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
      ), # Ethnicity [CHRT]
      O = case_when(
        SocioEconomicallyDisadvantaged == "Yes" ~ "Y",
        SocioEconomicallyDisadvantaged == "No" ~ "N",
        TRUE ~ ""
      ), # Economically disadvantaged indicator [CHRT]
      P = "", # 8th Grade Assessment Math
      Q = "", # 8th Grade Assessment ELA/Reading
      R = "", # High School Assessment Result Math
      S = "", # High School Assessment Result ELA/Reading
      T = case_when(
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
      ), # Disability code [CHRT]
      X = paste(
        if_else(MigrantEd == "Yes", "MIG_Y", "MIG_N"),
        if_else(FosterYouth == "Yes", "FOS_Y", "FOS_N"),
        if_else(Homeless == "Yes", "HOM_Y", "HOM_N"),
        if_else(UC_CSURequirementsMet == "Yes", "AG_Y", "AG_N"),
        if_else(Sealofbiliteracy == "Yes", "SSB_Y", "SSB_N"),
        sep= "."
      ), #Program Code [CHRT]
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
  print(header)
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
  group_by(SA, ACT, CDS, District, SchoolName) %>%
  summarise(n = n())
write_excel_csv(submission_count, "county_cohort_summary.csv")

service_accounts_w_submissions <- ref_sheets %>%
  left_join(submission_count) %>%
  arrange(District, HSName)
write_excel_csv(service_accounts_w_submissions, "service_account_analysis.csv")

reticulate::use_virtualenv('r-reticulate')
reticulate::py_require("paramiko")
reticulate::py_require("pandas")
reticulate::py_require("openpyxl")
