# Annual countywide graduate submission: cohort -> latest SINF names -> account mapping -> PH3/PD3/PT3 files. REQ-01 through REQ-04.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Annual class/path/window/run-date settings are centralized in annual_submission_config.R.
library(tidyverse)
library(readxl)
library(stringi)
library(arrow)
source("annual_submission_config.R")
project <- annual_submission_config()

# REQ-18 remains pending: a CHRT-to-15.2 crosswalk and permitted-charter
# registry are required before these sources can be combined safely. The previous
# loop silently discarded CHRT rows; reject their presence before any output writes.
chrt_files <- dir("data", pattern = "^CHRT.*")
if (length(chrt_files) > 0L) {
  stop("CHRT inputs are present: resolve REQ-18 input mapping before annual output generation")
}

countywide <- read_parquet(
  file = project$cohort_path
) %>% 
  mutate(
    BirthDate = lubridate::as_date(BirthDate, format = "%m/%d/%Y"),
    StudentEnrollmentStartDate =  lubridate::as_date(StudentEnrollmentStartDate,format = "%m/%d/%Y"),
    StudentEnrollmentExitDate = lubridate::as_date(StudentEnrollmentExitDate,format = "%m/%d/%Y"),
    DSEA = as.character(DSEA)
  ) %>%
  filter(
    StudentEnrollmentExitDate <= project$window_end,
    StudentEnrollmentExitDate >= project$window_start,
    !DistrictCode %in% project$excluded_districts # REQ-01: no graduate service account
) %>%
  mutate(CDS = paste0(DistrictCode, SchoolCode),
         .before = everything()) %>%
  distinct()

county_cohort <- countywide


# Get account reference sheets
ref_sheets <- read_excel("data/account_refs.xlsx", sheet = "Refs", col_types = "text")

# Do county wide data
county_grad <- county_cohort %>% filter(CohortCategory == "HSDiplomaGraduate")
graduate_class_years <- county_grad %>%
  filter(!is.na(StudentEnrollmentExitDate)) %>%
  transmute(
    GraduationClassYear = if_else(
      lubridate::month(StudentEnrollmentExitDate) >= 9L,
      lubridate::year(StudentEnrollmentExitDate) + 1L,
      lubridate::year(StudentEnrollmentExitDate)
    )
  ) %>%
  distinct(GraduationClassYear) %>%
  pull(GraduationClassYear)
if (length(graduate_class_years) != 1L) {
  stop(
    "Annual PH3 graduate submission must contain exactly one graduation class; found ",
    length(graduate_class_years)
  )
}

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

sanitize_names <- function(names) {
  new_names <- names %>%
    stri_trans_general(., "latin-ascii") %>% 
    gsub("\\.", "", .)
  return(new_names)
}

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

# REQ-19 / DEC-15: some charter SINF records store the school code as DistrictCode.
# The membership check below intentionally chooses that alternate district join key.
# REQ-20 / DEC-16: normalize the duplicated charter CDS to its authorizer CDS for accounts.
county_grad_w_accounts <- county_grad %>%
  filter(StudentEnrollmentExitDate <= project$window_end,
         StudentEnrollmentExitDate >= project$window_start) %>%
  mutate(
    join_code = if_else(SchoolCode %in% sinf_merge$DistrictCode, SchoolCode, DistrictCode)
  ) %>%
  left_join(sinf_merge, by = c("SSID", "join_code" = "DistrictCode")) %>%
  mutate(
    CDS = if_else(CDS == '01252370125237', '33103300125237', CDS)
  ) %>%
  left_join(ref_sheets, by = "CDS") 

saveRDS(county_grad_w_accounts, "county_grad_w_accounts.rds")

missing_names <- county_grad_w_accounts %>%
  filter(is.na(LastName))

missing_service_accounts <- county_grad_w_accounts %>%
  filter(is.na(SA)) %>%
  distinct(CDS, District, SchoolName)

duplicated_students <- county_grad_w_accounts %>%
  group_by(SSID) %>%
  filter(n() > 1)

# Make studenttracker compliant student data
service_accounts <- ref_sheets %>%
  group_by(District, SA) %>%
  select(District, SA) %>%
  summarise()

# Suppress RCOE non-local charters
rcoe_charter_act <- c("054763", "054113", "050558")

for (i in 1:nrow(service_accounts)) {
  st_gradfile <- county_grad_w_accounts %>%
    filter(SA == service_accounts[i,] %>% pull(SA)) %>%
    filter(!ACT %in% rcoe_charter_act) %>%
  transmute(
    A = "PD3", # PD3
    B = "NO SSN", # SSN
    C = FirstName, # First Name [SINF]
    D = MiddleName, # Middle initial [SINF]
    E = LastName, # Last Name, NO Suffix [SINF]
    F = Suffix, # Name suffix [SINF]
    G = PrevFirst, # Previous first name [SINF]
    H = PrevLast, # Previous last name [SINF]
    I = format(BirthDate, format = "%Y%m%d"), # Birthday [CHRT]
    J = as.character(SSID), # Student ID Number [CHRT]
    K = "Regular Diploma", # Diploma Type
    L = format(StudentEnrollmentExitDate, format = "%Y%m%d"), # High School Graduation Date [CHRT]
    M = "N", # FERPA Block
    N = HSName, # High school name [RefSheet]
    O = ACT, # ACT Code  [RefSheet]
    P = if_else(Gender %in% c("M", "F"),Gender,""), # Gender [CHRT]
    Q = case_when(
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
    R = case_when(
      substr(SocioEconomicallyDisadvantaged,1,1) == "Y" ~ "Y",
      substr(SocioEconomicallyDisadvantaged,1,1) == "N" ~ "N",
      TRUE ~ ""
      ), # Economically disadvantaged indicator [CHRT]
    S = "", # 8th Grade Assessment Math
    T = "", # 8th Grade Assessment ELA/Reading
    U = "", # High School Assessment Result Math
    V = "", # High School Assessment Result ELA/Reading
    W = case_when(
      substr(EnglishLearner,1,1) == "Y" ~ "Y",
      substr(EnglishLearner,1,1) == "N" ~ "N",
      TRUE ~ ""
    ), # EL indicator [CHRT]
    X = "", # Number of math semester completed
    Y = "", # Dual enrollment
    Z = case_when(
      substr(StudentswithDisabilities,1,1) == "Y" ~ "Y",
      substr(StudentswithDisabilities,1,1) == "N" ~ "N",
      TRUE ~ ""
    ), # Disability code [CHRT]
    AA = paste(
      if_else(substr(MigrantEd,1,1) == "Y", "MIG_Y", "MIG_N"),
      if_else(substr(FosterYouth,1,1) == "Y", "FOS_Y", "FOS_N"),
      if_else(substr(Homeless,1,1) == "Y", "HOM_Y", "HOM_N"),
      if_else(substr(UC_CSURequirementsMet,1,1) == "Y", "AG_Y", "AG_N"),
      if_else(substr(Sealofbiliteracy,1,1) == "Y", "SSB_Y", "SSB_N"),
      sep= "."
    ), #Program Code [CHRT]
    AB = "ED" 
  )
  header <- tibble(
    A="PH3",
    B=service_accounts[i,] %>% pull(SA),
    C=service_accounts[i,] %>% pull(District),
    D="P",
    E=project$run_date,
    F=project$school_year
  ) 
  trailer <- tibble(
    A = "PT3",
    B = as.character((nrow(st_gradfile) + 2))
  )
  final_file <- bind_rows(
    header,
    st_gradfile,
    trailer
  )
  write_delim(
    final_file,
    file = paste0(
      "submissionfiles/",
      project$run_date,
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
      "submissionfiles/test_file/",
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

reticulate::py_require("paramiko")
reticulate::py_require("pandas")
reticulate::py_require("openpyxl")
