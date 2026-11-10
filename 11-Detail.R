# Annual detail enrichment: combine NSC returns, RCCD matches, cohort demographics, and program indicators. Outputs contain student-level information. REQ-16.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(tidyverse)
library(arrow)
library(readxl)

get_default_grad_file_path <- function(cohort_year) {
  local_default <- sprintf(
    "data/ClassOf%s-ClassOf%s_152_cohort_outcomes.parquet",
    cohort_year,
    as.integer(cohort_year) + 3
  )
  if (file.exists(local_default)) return(local_default)

  local_any <- list.files("data", pattern = "^ClassOf\\d+-ClassOf\\d+_152_cohort_outcomes\\.parquet$", full.names = TRUE)
  if (length(local_any) > 0) {
    info <- file.info(local_any)
    latest_local <- rownames(info)[which.max(info$mtime)]
    return(latest_local)
  }

  sprintf(
    "s3://example-studenttracker-bucket/calpads/county=33/district=00000/year=%s/month=08/day=26/ClassOf24-ClassOf27_152_cohort_outcomes.parquet",
    as.integer(cohort_year) - 1
  )
}

get_default_avid_path <- function(cohort_year) {
  preferred <- sprintf("data/avid_%s.csv", cohort_year)
  if (file.exists(preferred)) return(preferred)
  fallback <- "data/avid_2024.csv"
  if (file.exists(fallback)) return(fallback)
  preferred
}

build_cde_snap_paths <- function(snap_code, years, bucket = "s3://example-studenttracker-bucket/calpads-snap/county=33/district=00000") {
  years <- as.integer(years)
  file_year <- paste0(years - 1, "-", years)
  paste0(bucket, "/year=", years, "/", file_year, "_", snap_code, "_snap.parquet")
}

sync_latest_calkids_multiyear <- function(
    source_dir = "../20240418 CalKIDS Match",
    dest_path = "data/calkids_multiyear_analysis.parquet"
) {
  if (!dir.exists(source_dir)) {
    message(sprintf("CalKIDS source dir not found: %s (using existing %s if present)", source_dir, dest_path))
    return(invisible(dest_path))
  }

  candidates <- list.files(
    source_dir,
    pattern = "^calkids_multiyear_analysis\\.parquet$",
    full.names = TRUE,
    recursive = TRUE
  )
  if (length(candidates) == 0) {
    message(sprintf("No calkids_multiyear_analysis.parquet found under %s (using existing %s if present)", source_dir, dest_path))
    return(invisible(dest_path))
  }

  info <- file.info(candidates)
  latest_path <- rownames(info)[which.max(info$mtime)]

  if (file.exists(dest_path)) {
    dest_mtime <- file.info(dest_path)$mtime
    if (!is.na(dest_mtime) && dest_mtime >= info[latest_path, "mtime"]) {
      message(sprintf("CalKIDS multiyear already up to date: %s", dest_path))
      return(invisible(dest_path))
    }
  }

  ok <- file.copy(latest_path, dest_path, overwrite = TRUE)
  if (!ok) stop(sprintf("Failed to copy %s -> %s", latest_path, dest_path))
  message(sprintf("Updated CalKIDS multiyear: %s -> %s", latest_path, dest_path))
  invisible(dest_path)
}

get_latest_processed_eff_date <- function(processed_root = "processed") {
  dirs <- list.dirs(processed_root, recursive = FALSE, full.names = FALSE)
  dirs <- dirs[str_detect(dirs, "^\\d{8}$")]
  if (length(dirs) == 0) stop(sprintf("No processed eff_date folders found under %s", processed_root))
  sort(dirs, decreasing = TRUE)[[1]]
}

# load and combine the detail files
load_detail <- function(eff_date) {
  if (!dir.exists(file.path("processed", eff_date))) {
    stop(sprintf("processed/%s not found; set EFF_DATE to a folder under processed/", eff_date))
  }
  detail_files <- dir(path = paste0('processed/', eff_date), pattern = 'csv$', recursive = TRUE, full.names = TRUE)
  detail_files <- detail_files[!grepl("Top25", detail_files)]
  if (length(detail_files) == 0) stop(sprintf("No NSC detail CSVs found under processed/%s", eff_date))
  
  detail <- map_dfr(detail_files, ~ {
    print(.x)
    df <- read_csv(.x, col_types = cols(.default = col_character()))
    if (!("Your_Unique_Identifier" %in% names(df))) {
      message(sprintf("Skipping non-detail CSV (missing Your_Unique_Identifier): %s", .x))
      return(tibble())
    }
    df
  })
  
  detail_modified <- detail %>%
    mutate(
      SSID = str_replace_all(Your_Unique_Identifier, "_", ""),
      .before = everything()
    ) %>%
    mutate(
      source = "NSC"
    )
  
  # DEC-25: correction pairs are private input data, never source-code literals.
  # The sharing copy contains only the required headers; zero rows means no exclusions.
  # Keep any operational correction list local and exclude it from future sharing.
  duplicate_students <- read_csv(
    "data/nsc_duplicate_corrections.csv",
    col_types = cols(SSID = col_character(), Last_Name = col_character())
  ) %>% select(SSID, Last_Name)
  
  detail_modified_fix <- detail_modified %>%
    anti_join(duplicate_students, by = c("SSID", "Last_Name"))
  
  return(detail_modified_fix)
}

# Load RCC Data 
load_rcc <- function(path) {
  rcc_detail <- read_parquet(path) %>%
    mutate(
      `College_Code/Branch` = paste0(`School Code`, '-', `Branch Code`)
    )
  
  return(rcc_detail)
}


# Import most recent grad file to match in AI Code and School
load_grads <- function(grad_file_path, school_codes_path, cohort_year = NULL) {
  grad_file <- read_parquet(grad_file_path) 
  
  school_codes <- read_excel(school_codes_path) %>%
    transmute(
      CDS = CDS,
      High_School_Code = ACT
    )
  
  final_grad <- grad_file %>%
    mutate(CDS = paste0(DistrictCode, SchoolCode)) %>%
    left_join(school_codes, by = 'CDS') %>%
    filter(
      CohortCategory == 'HSDiplomaGraduate',
      if (!is.null(cohort_year)) CohortYear == cohort_year else TRUE,
    ) %>%
    transmute(
      SSID = SSID, 
      High_School_Code = High_School_Code,
      High_School_Grad_Date = mdy(StudentEnrollmentExitDate)
      ) %>%
    filter(!is.na(High_School_Code))
  
  return(final_grad)
}

# Convert RCC detail to conforming format
convert_rcc_to_nsc <- function(rcc_detail, final_grad) {
  rcc_conformed_detail <- rcc_detail %>%
    filter(!(`Enrollment Status` %in% c("G","W", "D")),
           !is.na(SSID)) %>%
    left_join(final_grad, by = 'SSID') %>%
    transmute(
      SSID = SSID,
      Your_Unique_Identifier = "",
      First_Name = `First Name`,
      Middle_Name = `Middle Name`,
      Last_Name = `Last Name`,
      Name_Suffix = `Name Suffix`,
      Requester_Return_Field = "",
      `Record_Found_Y/N` = "Y",
      High_School_Code = High_School_Code,
      High_School_Grad_Date = format(High_School_Grad_Date,"%Y%m%d"),
      `College_Code/Branch` = `College_Code/Branch`,
      `College_Name` = case_when(
        `College_Code/Branch` == '041761-00' ~ 'NORCO COLLEGE',
        `College_Code/Branch` == '001270-00' ~ 'RIVERSIDE CITY COLLEGE',
        `College_Code/Branch` == '041735-00' ~ 'MORENO VALLEY COLLEGE',
      ),
      College_State = "CA",
      `2-Year/4-Year` = "2-year",
      `Public/Private` = "Public",
      Enrollment_Begin = `Term Begin Date`,
      Enrollment_End = `Term End Date`,
      Enrollment_Status = `Enrollment Status`,
      Graduated = "",
      Graduation_Date = "",
      Degree_Title = "", 
      Major = `Major Course of Study 1`,
      College_Sequence = "",
      Program_Code = `NCES CIP Code for Major 1`,
      source = "RCCD"
    )
}


# Remove RCCD students already in NSC for same term
filter_rcc_for_nsc <- function(nsc_details, rcc_details) {
  rcc_already_reported_keys <- nsc_details %>%
    filter(
      `College_Code/Branch` %in% c('041761-00', '001270-00', '041735-00')
    ) %>%
    select(
      SSID,
      Enrollment_Begin,
      `College_Code/Branch`
    ) %>%
    distinct()
  
  rcc_conformed_detail_no_dups <- rcc_details %>%
    anti_join(
      rcc_already_reported_keys,
      by = c('SSID', 'Enrollment_Begin', 'College_Code/Branch')
    )
  
  return(rcc_conformed_detail_no_dups)
}

# Combine the two 
combine_rcc_nsc <- function(nsc_detail, rcc_only_detail, rcc_full_data) {
  nsc_details_remove_n <- nsc_detail %>%
    filter(!(SSID %in% rcc_only_detail$SSID & `Record_Found_Y/N` == 'N'))  
  
  nsc_combined <- nsc_details_remove_n %>%
    bind_rows(rcc_only_detail)
  
  first_non_empty <- function(x) {
    x <- x[!is.na(x) & x != ""]
    if (length(x) == 0) return(NA_character_)
    x[[1]]
  }
  
  rcc_major_lookup <- rcc_full_data %>%
    select(
      SSID,
      Enrollment_Begin,
      `College_Code/Branch`,
      Major,
      Program_Code
    ) %>%
    group_by(
      SSID,
      Enrollment_Begin,
      `College_Code/Branch`
    ) %>%
    summarise(
      Major_rcc = first_non_empty(Major),
      Program_Code_rcc = first_non_empty(Program_Code),
      .groups = "drop"
    )
  
  nsc_combined_all_majors <- nsc_combined %>%
    left_join(
      rcc_major_lookup,
      suffix = c("", "_rcc"),
      by = c('SSID', 'Enrollment_Begin', 'College_Code/Branch'),
      relationship = 'many-to-one'
    ) %>%
    mutate(
      Major = if_else(is.na(Major), Major_rcc, Major),
      Program_Code = if_else(is.na(Program_Code), Program_Code_rcc, Program_Code)
    ) %>%
    select(
      -Major_rcc,
      -Program_Code_rcc
    )
  
  return(nsc_combined_all_majors)
}

load_grad_demos <- function(grad_file_path, avid_path, cte_paths, course_paths, calkids_path, acct_ref) {
  # Simple list of AVID students
  avid <- read_csv(avid_path, col_types = cols(.default = col_character()))
  
  # CTE Pathway details
  cte <- map_dfr(cte_paths, read_parquet)
  cte_merge <- cte %>%
    select(
      SSID,
      IndustrySector,
      CTEPathWay
    ) %>%
    unique() %>%
    group_by(SSID) %>%
    mutate(
      pathway_sequence = row_number()
    ) %>%
    pivot_wider(
      names_from = pathway_sequence,
      values_from = c(IndustrySector, CTEPathWay),
      names_sep = "_",
      names_vary = "slowest"
    ) 
  
  # Import courses
  courses <- map_dfr(course_paths, read_parquet)
  ap_codes <- c(
    "9002", "9003", "9004", "9005", "9066", "9067", "9118", "9119", "9146", "9147", 
    "9148", "9149", "9150", "9151", "9152", "9153", "9191", "9192", "9193", "9194", 
    "9195", "9196", "9197", "9198", "9199", "9225", "9226", "9266", "9267", "9268", 
    "9300", "9344", "9345", "9346", "9347", "9348", "9349", "9350", "9361", "9362", 
    "9002", "9003", "9004", "9005", "9066", "9067", "9118", "9119", "9146", "9147", 
    "9148", "9149", "9150", "9151", "9152", "9153", "9191", "9192", "9193", "9194", 
    "9195", "9196", "9197", "9198", "9199", "9225", "9226", "9266", 
    "9267", "9268", "9300", "9344", "9345", "9346", "9347", "9348", "9349", "9350", 
    "9361", "9362"
  )
  ib_codes <- c(
    "9007", "9052", "9068", "9069", "9081", "9093", "9095", "9115", "9116", "9117", 
    "9140", "9141", "9142", "9143", "9144", "9145", "9182", "9183", "9184", "9185", 
    "9186", "9187", "9188", "9189", "9190", "9269", "9270", "9271", "9272", "9281", 
    "9282", "9283", "9284", "9302", "9351", "9352", "9354", "9355", "9356", "9357", 
    "9006", "9007", "9052", "9065", "9068", "9069", "9081", "9093", "9094", "9095", 
    "9113", "9114", "9115", "9116", "9117", "9138", "9139", "9140", "9141", "9142", 
    "9143", "9144", "9145", "9181", "9182", "9183", "9184", "9185", "9186", "9187", 
    "9188", "9189", "9190", "9235", "9261", "9262", "9263", "9264", "9265", "9269", 
    "9270", "9271", "9272", "9281", "9282", "9283", "9284", "9285", "9286", "9301", 
    "9302", "9317", "9351", "9352", "9353", "9354", "9355", "9356", "9357", "9382"
  )
  college_codes <- c(
    "9020", "9082", "9096", "9120", "9154", 
    "9200", "9218", "9227", "9273", "9303", "9358"
  )
  ap_count <- courses %>%
    filter(str_starts(StateCourse,paste(ap_codes,collapse="|"))) %>%
    group_by(SSID) %>%
      count(name = "ap_course_count")
  ib_count <- courses %>%
    filter(str_starts(StateCourse,paste(ib_codes,collapse="|"))) %>%
    group_by(SSID) %>%
      count(name = "ib_course_count")
  college_non_cte_count <- courses %>%
    filter(str_starts(StateCourse,paste(college_codes,collapse="|"))) %>%
    group_by(SSID) %>%
      count(name = "college_non_cte_count")
  
  # School details
  schools <- read_excel(acct_ref) %>%
  select(
    CDS,
    District, 
    HSName
  )
  
  # CALKIDS
  calkids_max_date <- read_parquet(file = calkids_path) %>%
    group_by(SSID) %>%
    summarise(
      date = max(date)
    ) 
  
  calkids <- read_parquet(file = calkids_path) %>%
    inner_join(calkids_max_date) %>%
    select(
      SSID, 
      last_CALKIDS_update = date,
      CALKIDS_Eligible = `CalKids Eligible`,
      CALKIDS_Registered = `Registered or Not Registered`
    ) %>%
    distinct()

  grad_file <- read_parquet(
    grad_file_path
  )  %>%
    mutate(
      CalpadsGradDate = format(mdy(StudentEnrollmentExitDate), '%Y%m%d')
    ) %>%
    filter(
      StudentExitReason == "E230",
      EnrollmentStatus == "10"
    ) %>%
    arrange(
      SSID,
      desc(StudentEnrollmentExitDate)
    ) %>%
    distinct(SSID, .keep_all = TRUE) %>%
    select(
      SSID,
      DistrictCode,
      SchoolCode,
      StudentswithDisabilities,
      SocioEconomicallyDisadvantaged,
      EnglishLearner,
      FosterYouth,
      Homeless,
      Sealofbiliteracy,
      UC_CSURequirementsMet,
      CohortYear,
      CalpadsGradDate
    ) %>%
    mutate(AVID = if_else(SSID %in% avid$SSID, "Yes", "No"), .after = Homeless) %>%
    left_join(calkids, by = 'SSID') %>%
    left_join(cte_merge, by = 'SSID') %>%
    mutate(CTE_Completer = if_else(is.na(CTEPathWay_1), "No", "Yes"), .after = UC_CSURequirementsMet) %>%
    left_join(ap_count, by = 'SSID') %>%
    left_join(ib_count, by = 'SSID') %>%
    left_join(college_non_cte_count, by = 'SSID') %>%
    mutate(
      CDS = paste0(DistrictCode, SchoolCode), .before = DistrictCode
    ) %>%
    left_join(
      schools,
      by = 'CDS'
    ) %>%
    relocate(
      District:HSName,
      .after = SchoolCode
    )
  
  return(grad_file)
} 

single_year_nsc <- function(detail_file, grad_file, cohort_year, grad_start_date) {
  final_file <- detail_file %>%
  left_join(
    grad_file ,
    by = 'SSID',
    relationship = 'many-to-one'
  ) %>%
  filter(
    CohortYear == cohort_year,
    (High_School_Grad_Date > grad_start_date) | (CalpadsGradDate > grad_start_date)
  ) %>%
    arrange(
      District,
      HSName,
      Last_Name,
      First_Name
    )
  return(final_file)
}
  

### Run the script
EFF_DATE <- Sys.getenv("EFF_DATE", unset = NA_character_)
if (is.na(EFF_DATE) || !dir.exists(file.path("processed", EFF_DATE))) {
  EFF_DATE <- get_latest_processed_eff_date()
}

COHORT_YEAR <- Sys.getenv("COHORT_YEAR", unset = "2025")
NSC_GRAD_START <- Sys.getenv(
  "NSC_GRAD_START",
  unset = sprintf("%s0801", as.integer(COHORT_YEAR) - 1)
)

GRAD_FILE_PATH <- Sys.getenv("GRAD_FILE_PATH", unset = get_default_grad_file_path(COHORT_YEAR))
CALKIDS_PATH <- Sys.getenv("CALKIDS_PATH", unset = "data/calkids_multiyear_analysis.parquet")
CALKIDS_SOURCE_DIR <- Sys.getenv("CALKIDS_SOURCE_DIR", unset = "../20240418 CalKIDS Match")
sync_latest_calkids_multiyear(source_dir = CALKIDS_SOURCE_DIR, dest_path = CALKIDS_PATH)
AVID_PATH <- Sys.getenv("AVID_PATH", unset = get_default_avid_path(COHORT_YEAR))
SNAP_YEARS_BACK <- as.integer(Sys.getenv("SNAP_YEARS_BACK", unset = "4"))
SNAP_LATEST_YEAR <- as.integer(Sys.getenv("SNAP_LATEST_YEAR", unset = COHORT_YEAR))
SNAP_YEARS <- seq(SNAP_LATEST_YEAR, SNAP_LATEST_YEAR - (SNAP_YEARS_BACK - 1))

nsc_detail <- load_detail(eff_date = EFF_DATE)
rcc_detail <- load_rcc(path = 'data/rccd_matched_ssid.parquet')
grads <- load_grads(
  grad_file_path = GRAD_FILE_PATH,
  school_codes_path = 'data/account_refs.xlsx',
  cohort_year = COHORT_YEAR
)
rcc_nsc_format <- convert_rcc_to_nsc(rcc_detail, grads)
rcc_no_nsc <- filter_rcc_for_nsc(nsc_detail, rcc_nsc_format)
full_details <- combine_rcc_nsc(nsc_detail, rcc_no_nsc, rcc_nsc_format)
grad_demos <- load_grad_demos(
  grad_file_path = GRAD_FILE_PATH,
  avid_path = AVID_PATH,
  calkids_path = CALKIDS_PATH,
  cte_paths = build_cde_snap_paths("320", SNAP_YEARS),
  course_paths = build_cde_snap_paths("311", SNAP_YEARS),
  acct_ref = 'data/account_refs.xlsx'
)
class_w_demos <- single_year_nsc(full_details, grad_demos, COHORT_YEAR, NSC_GRAD_START)

# Save files
write_parquet(
  class_w_demos,
  sink = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_detail.parquet'),
  compression = 'snappy'
)
write_excel_csv(
  class_w_demos,
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_detail.csv'),
  na = ""
)

# School files
schools <- class_w_demos %>%
  select(CDS, District, HSName) %>%
  distinct %>%
  filter(!is.na(HSName))

districts <- schools %>%
  select( District) %>%
  distinct()

filter_and_write <- function(class_file, CDS, District, HSName) {
  dir.create(paste0('full_detail/',District), showWarnings = FALSE)
  if (is.na(HSName)) {
    data <- class_file %>%
      filter(District == !!District)
    
    write_excel_csv(
      data,
        file = paste0('full_detail/', District, '/_', District, '_ClassOf25_NSC_details.csv'),
        na = "",
      )
  } else {
    data <- class_file %>%
      filter(CDS == !!CDS) 
      write_excel_csv(
        data,
        file = paste0('full_detail/', District, '/', HSName, '_ClassOf25_NSC_details.csv'),
        na = "",
      )
  }
}

walk(
  seq_len(nrow(schools)),
  ~ filter_and_write(
    class_file = class_w_demos,
    CDS = schools$CDS[.x],
    District = schools$District[.x],
    HSName = schools$HSName[.x]
  )
)

walk(
  seq_len(nrow(districts)),
  ~ filter_and_write(
    class_file = class_w_demos,
    CDS = NA,
    District = districts$District[.x],
    HSName = NA
  )
)

# CSU File
csu <- c(
  "001143-00",  "001144-00",
  "001149-00",  "039803-00",
  "007993-00",  "001146-00",
  "001141-00",  "001138-00",
  "001147-00",  "001137-00",
  "001139-00",  "001140-00",
  "032603-00",  "001142-00",
  "030113-00",  "001157-00",
  "001134-00",  "001153-00",
  "001151-00",  "001155-00",
  "001154-00",  "001156-00",
  "001150-00"
)
ucr <- "001316-00"
rcc <- c(
  "041761-00", "001270-00", "041735-00"
)
write_excel_csv(
  class_w_demos %>%
    filter(`College_Code/Branch` %in% csu) %>%
    unique() %>%
    arrange(College_Name),
  na = '',
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_csu.csv')
)
for (i in csu) {
  temp_csu <- class_w_demos %>%
    filter(`College_Code/Branch` == i) %>%
    select(SSID:College_Name, District, HSName, CALKIDS_Eligible, CALKIDS_Registered) %>%
    unique()
  csu_name <- temp_csu$College_Name[1]
  write_excel_csv(
    temp_csu,
    na = '',
    file = paste0('full_detail/_csu/class_of_', COHORT_YEAR, '_calkids_', csu_name, '.csv')
  )
}
write_excel_csv(
  class_w_demos %>%
    filter(`College_Code/Branch` == "001316-00") %>%
    arrange(College_Name) %>%
    unique(),
  na = '',
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_ucr.csv')
)
write_excel_csv(
  class_w_demos %>%
    filter(`College_Code/Branch` == "001316-00") %>%
    select(SSID:College_Name, District, HSName, CALKIDS_Eligible, CALKIDS_Registered) %>%
    arrange(College_Name) %>%
    unique(),
  na = '',
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_ucr_calkids.csv')
)
write_excel_csv(
  class_w_demos %>%
    filter(`College_Code/Branch` %in% rcc) %>%
    arrange(College_Name) %>%
    unique(),
  na = '',
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_rccd.csv')
)
write_excel_csv(
  class_w_demos %>%
    filter(`College_Code/Branch` %in% rcc) %>%
    select(SSID:College_Name, District, HSName, CALKIDS_Eligible, CALKIDS_Registered) %>%
    arrange(College_Name) %>%
    unique(),
  na = '',
  file = paste0('full_detail/class_of_', COHORT_YEAR, '_nsc_rccd_calkids.csv')
)


### Diagnostics
# Get count of RCC students from cohort
detail_rcc_prefix <- nsc_detail %>%
  filter(`College_Code/Branch` %in% c('041761-00', '001270-00', '041735-00'),
                                      High_School_Grad_Date > NSC_GRAD_START
)

# Students with no details in detail with records from RCC
no_detail <- nsc_detail %>%
  filter(`Record_Found_Y/N` == 'N')

no_detail_in_rcc <- no_detail %>%
  filter(High_School_Grad_Date > NSC_GRAD_START, SSID %in% rcc_detail$SSID)

# Duplicate NSC records
duplicate_nsc <- nsc_detail %>% 
  filter(`College_Code/Branch` %in% c('041761-00', '001270-00', '041735-00'), 
         !is.na(Enrollment_Begin)
         ) %>% 
  group_by(SSID, `College_Code/Branch`, Enrollment_Begin) %>% 
  count()

# Summary
class_summary <- class_w_demos %>%
  group_by(College_Name, `College_Code/Branch`) %>%
  summarise(
    n = n()
  )
