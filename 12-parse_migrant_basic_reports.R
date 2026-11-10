# Parse districtwide migrant BASIC workbooks into normalized summary tables. Confirm report layout and districtwide scope before reuse. REQ-14, REQ-15.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
suppressPackageStartupMessages({
  library(dplyr)
  library(purrr)
  library(readxl)
  library(stringr)
  library(tidyr)
})

args <- commandArgs(trailingOnly = TRUE)
input_dir <- if (length(args) >= 1) args[[1]] else "migrant_workflow/data/excel"
output_dir <- if (length(args) >= 2) args[[2]] else "migrant_workflow/parsed"

category_map <- c(
  "Count of Students Enrolled in College the Fall Immediately Following Graduation From High School" = "Immediate Enrollment",
  "Count of Students Enrolled in College at Any Time During the First Year After High School" = "First Year Enrollment",
  "Count of Students Enrolled in College at Any Time During the First Two Years After High School" = "First Two Years Enrollment",
  "Count of Students Enrolled in College the First Year After High School Who Returned for a" = "Returned for second year",
  "Count of High School Graduates with a College Degree" = "High School Graduates with a College Degree",
  "Time to College Graduation Within Six Years (Associate's, Bachelor's and Higher)" = "Time to College Graduation"
)

min_class_year <- 2018L

summary_allowed_groups <- list(
  "Immediate Enrollment" = c(
    "Total in the Class",
    "Total Enrolled",
    "Total in Public",
    "Total in Private",
    "Total in 4-Year",
    "Total in 2-Year",
    "Total In-State",
    "Total Out-Of-State"
  ),
  "First Year Enrollment" = c(
    "Total in the Class",
    "Total Enrolled",
    "Total in Public",
    "Total in Private",
    "Total in 4-Year",
    "Total in 2-Year",
    "Total In-State",
    "Total Out-Of-State"
  ),
  "First Two Years Enrollment" = c(
    "Total in the Class",
    "Total Enrolled",
    "Total in Public",
    "Total in Private",
    "Total in 4-Year",
    "Total in 2-Year",
    "Total In-State",
    "Total Out-Of-State"
  ),
  "Returned for second year" = c(
    "Total in the Class",
    "Enrolled Anywhere 1st Year",
    "Enrolled Anywhere 2nd Year",
    "In Public 1st Year",
    "In Private 1st Year",
    "In 4-Year 1st Year",
    "In 2-Year 1st Year",
    "In-State 1st Year",
    "Out-of-State 1st Year"
  ),
  "High School Graduates with a College Degree" = c(
    "Total in the Class",
    "Total With a Degree",
    "Total from Public",
    "Total from Private",
    "Total from 4-Year",
    "Total from 2-Year",
    "Total In-State",
    "Total Out-Of-State"
  ),
  "Time to College Graduation" = c(
    "Total in the Class",
    "Graduated in 2 Years or Less",
    "Graduated in 3 Years",
    "Graduated in 4 Years",
    "Graduated in 5 Years",
    "Graduated in 6 Years"
  )
)

persistence_groups <- c(
  "All Institutions",
  "Public Institutions",
  "Private Institutions",
  "4-Year Institutions",
  "2-Year Institutions",
  "In-State Institutions",
  "Out-of-State Institutions"
)

progress_allowed_groups <- c(
  "New to College",
  "Persisted",
  "Returned After Stop Out",
  "No Longer Enrolled & Not Graduated",
  "Graduated",
  "Not in NSC to Date"
)

normalize_cell <- function(x) {
  x <- as.character(x)
  x <- str_replace_all(x, "[\r\n]+", " ")
  x <- str_squish(x)
  x[x %in% c("", "NA", "N/A")] <- NA_character_
  x
}

compact_block <- function(block) {
  keep_cols <- vapply(block, function(col) any(!is.na(col) & col != ""), logical(1))
  block[, keep_cols, drop = FALSE]
}

coerce_number <- function(x) {
  cleaned <- str_replace_all(x, ",", "")
  cleaned <- ifelse(str_detect(cleaned, "^-?\\d+(\\.\\d+)?$"), cleaned, NA_character_)
  as.numeric(cleaned)
}

first_numeric <- function(x) {
  values <- coerce_number(x)
  values <- values[!is.na(values)]
  if (length(values) == 0) {
    return(NA_real_)
  }
  values[[1]]
}

sum_or_na <- function(x) {
  if (all(is.na(x))) {
    return(NA_real_)
  }
  sum(x, na.rm = TRUE)
}

normalize_group <- function(x) {
  case_when(
    x == "Total In the Class" ~ "Total in the Class",
    x == "Total Out-of-State" ~ "Total Out-Of-State",
    TRUE ~ x
  )
}

extract_effective_date <- function(first_col_values) {
  idx <- which(str_detect(first_col_values, "^Effective Date = "))
  if (length(idx) == 0) {
    return(NA_character_)
  }
  str_remove(first_col_values[[idx[[1]]]], "^Effective Date =\\s*")
}

parse_effective_year <- function(effective_date) {
  as.integer(str_extract(effective_date, "\\d{4}$"))
}

apply_summary_maturity <- function(df) {
  if (nrow(df) == 0) {
    return(df)
  }

  df %>%
    mutate(
      class_year_int = as.integer(class_year),
      effective_year = parse_effective_year(effective_date),
      maturity_max_year = case_when(
        category == "Returned for second year" ~ effective_year - 3L,
        category %in% c(
          "High School Graduates with a College Degree",
          "Time to College Graduation"
        ) ~ effective_year - 7L,
        TRUE ~ NA_integer_
      )
    ) %>%
    filter(
      !is.na(class_year_int),
      class_year_int >= min_class_year,
      is.na(maturity_max_year) | class_year_int <= maturity_max_year
    ) %>%
    select(-class_year_int, -effective_year, -maturity_max_year)
}

apply_progress_maturity <- function(df) {
  if (nrow(df) == 0) {
    return(df)
  }

  df %>%
    mutate(class_year_int = as.integer(class_year)) %>%
    filter(!is.na(class_year_int), class_year_int >= min_class_year) %>%
    select(-class_year_int)
}

prepare_block <- function(df, start_row, end_row) {
  block <- df[start_row:end_row, , drop = FALSE]
  compact_block(block)
}

parse_summary_block <- function(df, start_row, end_row, district, source_file) {
  block <- prepare_block(df, start_row, end_row)
  title <- block[[1]][[1]]
  category <- unname(category_map[[title]])
  effective_date <- extract_effective_date(block[[1]])
  header_rows <- which(block[[1]] == "Class of")

  if (length(header_rows) == 0) {
    stop(sprintf("Could not find 'Class of' header in %s at row %s", source_file, start_row))
  }

  panel_ends <- c(header_rows[-1] - 1, nrow(block))
  panel_tables <- vector("list", length(header_rows))

  for (i in seq_along(header_rows)) {
    header_row <- header_rows[[i]]
    panel_end <- panel_ends[[i]]
    header_cols <- which(!is.na(block[header_row, ]) & block[header_row, ] != "")
    header_cols <- setdiff(header_cols, 1)
    if (length(header_cols) == 0) {
      next
    }

    class_years <- unlist(block[header_row, header_cols], use.names = FALSE)
    data_rows <- seq.int(header_row + 1, panel_end)
    data_rows <- data_rows[!is.na(block[data_rows, 1]) & block[data_rows, 1] != ""]
    if (length(data_rows) == 0) {
      next
    }

    data <- block[data_rows, c(1, header_cols), drop = FALSE]
    names(data) <- c("Group", class_years)

    panel_tables[[i]] <- data %>%
      mutate(
        Group = normalize_group(Group)
      ) %>%
      filter(Group %in% summary_allowed_groups[[category]]) %>%
      mutate(
        row_order = row_number()
      ) %>%
      pivot_longer(
        cols = -c(Group, row_order),
        names_to = "class_year",
        values_to = "n_text"
      ) %>%
      mutate(
        district = district,
        source_file = source_file,
        effective_date = effective_date,
        category = category,
        n = coerce_number(n_text)
      ) %>%
      select(district, source_file, effective_date, category, Group, class_year, n, row_order)
  }

  long <- bind_rows(panel_tables)
  if (nrow(long) == 0) {
    return(tibble())
  }

  if (identical(category, "Returned for second year")) {
    pair_index <- ceiling((long$row_order - 1) / 2)
    persistence_group <- rep(NA_character_, nrow(long))
    persistence_group[long$row_order > 1] <- persistence_groups[pmin(pair_index[long$row_order > 1], length(persistence_groups))]

    long <- long %>%
      mutate(
        persistence_group = persistence_group,
        persistence_stage = case_when(
          row_order == 1 ~ "class_size",
          (row_order %% 2) == 0 ~ "first_year",
          TRUE ~ "second_year"
        )
      )
  }

  long
}

parse_progress_block <- function(df, start_row, end_row, district, source_file) {
  block <- prepare_block(df, start_row, end_row)
  title <- block[[1]][[1]]
  class_year <- str_match(title, "^Count of Class (\\d{4})\\s+Postsecondary Enrollment and Progress$")[, 2]

  if (is.na(class_year)) {
    stop(sprintf("Could not parse class year from progress title in %s at row %s", source_file, start_row))
  }

  total_in_class <- first_numeric(unlist(block[2, -1], use.names = FALSE))
  header_row <- which(block[[1]] == "Academic Years")[1]

  if (is.na(header_row)) {
    stop(sprintf("Could not find 'Academic Years' header in %s at row %s", source_file, start_row))
  }

  academic_years <- unlist(block[header_row, -1], use.names = FALSE)
  academic_years <- academic_years[!is.na(academic_years) & academic_years != ""]
  if (length(academic_years) == 0) {
    return(tibble())
  }

  data_rows <- seq.int(header_row + 1, nrow(block))
  data_rows <- data_rows[!is.na(block[data_rows, 1]) & block[data_rows, 1] != ""]
  if (length(data_rows) == 0) {
    return(tibble())
  }

  build_row <- function(row_index) {
    label <- block[row_index, 1][[1]]
    values <- unlist(block[row_index, -1], use.names = FALSE)
    values <- values[!is.na(values) & values != ""]
    values <- values[seq_len(min(length(values), length(academic_years)))]
    if (length(values) < length(academic_years)) {
      values <- c(values, rep(NA_character_, length(academic_years) - length(values)))
    }

    tibble(
      Group = label,
      !!!setNames(as.list(values), academic_years)
    )
  }

  data <- bind_rows(lapply(data_rows, build_row))

  data %>%
    filter(Group %in% progress_allowed_groups) %>%
    mutate(row_order = row_number()) %>%
    pivot_longer(
      cols = -c(Group, row_order),
      names_to = "academic_year",
      values_to = "n_text"
    ) %>%
    mutate(
      district = district,
      source_file = source_file,
      class_year = class_year,
      total_in_class = total_in_class,
      n = coerce_number(n_text)
    ) %>%
    select(district, source_file, class_year, total_in_class, academic_year, Group, n, row_order)
}

parse_mci_block <- function(df, start_row, end_row, district, source_file) {
  block <- prepare_block(df, start_row, end_row)
  header_row <- which(block[[1]] == "Name")[1]

  if (is.na(header_row)) {
    stop(sprintf("Could not find 'Name' header in %s at row %s", source_file, start_row))
  }

  header_cols <- which(!is.na(block[header_row, ]) & block[header_row, ] != "")
  header_names <- unlist(block[header_row, header_cols], use.names = FALSE)
  col_map <- setNames(header_cols, header_names)
  required <- c("Name", "Rank", "State", "Level", "Type", "Total")

  if (!all(required %in% names(col_map))) {
    stop(sprintf("MCI header columns missing in %s at row %s", source_file, start_row))
  }

  data_rows <- seq.int(header_row + 1, nrow(block))
  data_rows <- data_rows[!is.na(block[data_rows, 1]) & block[data_rows, 1] != ""]
  if (length(data_rows) == 0) {
    return(tibble())
  }

  tibble(
    district = district,
    source_file = source_file,
    Name = block[[col_map[["Name"]]]][data_rows],
    Rank = coerce_number(block[[col_map[["Rank"]]]][data_rows]),
    State = block[[col_map[["State"]]]][data_rows],
    Level = block[[col_map[["Level"]]]][data_rows],
    Type = block[[col_map[["Type"]]]][data_rows],
    Total = coerce_number(block[[col_map[["Total"]]]][data_rows])
  )
}

parse_workbook <- function(path) {
  df <- read_excel(
    path,
    col_names = FALSE,
    col_types = "text",
    .name_repair = "minimal"
  ) %>%
    as.data.frame(stringsAsFactors = FALSE)

  df[] <- lapply(df, normalize_cell)
  district <- df[[1]][which(!is.na(df[[1]]) & df[[1]] != "")[1]]
  first_col <- df[[1]]
  row_text <- apply(df, 1, function(row) paste(na.omit(row), collapse = " | "))

  section_rows <- which(
    first_col %in% names(category_map) |
      str_detect(first_col, "^Count of Class \\d{4}\\s+Postsecondary Enrollment and Progress$") |
      str_detect(row_text, "^Most Common Institutions of Enrollment")
  )

  if (length(section_rows) == 0) {
    stop(sprintf("No recognizable sections found in %s", path))
  }

  block_ends <- c(section_rows[-1] - 1, nrow(df))

  summary_tables <- list()
  progress_tables <- list()
  mci_tables <- list()

  for (i in seq_along(section_rows)) {
    start_row <- section_rows[[i]]
    end_row <- block_ends[[i]]
    title <- first_col[[start_row]]
    row_label <- row_text[[start_row]]

    if (!is.na(title) && title %in% names(category_map)) {
      summary_tables[[length(summary_tables) + 1]] <- parse_summary_block(
        df = df,
        start_row = start_row,
        end_row = end_row,
        district = district,
        source_file = basename(path)
      )
    } else if (!is.na(title) && str_detect(title, "^Count of Class \\d{4}\\s+Postsecondary Enrollment and Progress$")) {
      progress_tables[[length(progress_tables) + 1]] <- parse_progress_block(
        df = df,
        start_row = start_row,
        end_row = end_row,
        district = district,
        source_file = basename(path)
      )
    } else if (str_detect(row_label, "^Most Common Institutions of Enrollment")) {
      mci_tables[[length(mci_tables) + 1]] <- parse_mci_block(
        df = df,
        start_row = start_row,
        end_row = end_row,
        district = district,
        source_file = basename(path)
      )
    }
  }

  list(
    summary = bind_rows(summary_tables),
    progress = bind_rows(progress_tables),
    mci = bind_rows(mci_tables)
  )
}

validate_summary_counts <- function(summary_metrics) {
  class_sizes <- summary_metrics %>%
    filter(Group == "Total in the Class") %>%
    transmute(
      district,
      category,
      class_year,
      class_size = n
    )

  checked <- summary_metrics %>%
    left_join(class_sizes, by = c("district", "category", "class_year")) %>%
    mutate(
      invalid_count = Group != "Total in the Class" &
        !is.na(n) &
        !is.na(class_size) &
        n > class_size
    )

  invalid_rows <- checked %>%
    filter(invalid_count)

  if (nrow(invalid_rows) > 0) {
    warning(sprintf(
      "Blanking %s summary rows where count exceeds class size",
      nrow(invalid_rows)
    ))
  }

  checked %>%
    mutate(n = if_else(invalid_count, NA_real_, n)) %>%
    select(-class_size, -invalid_count)
}

build_persistence_rates <- function(summary_metrics) {
  rates <- summary_metrics %>%
    filter(category == "Returned for second year", !is.na(persistence_group)) %>%
    transmute(
      district,
      source_file,
      effective_date,
      class_year,
      persistence_group,
      persistence_stage,
      n
    ) %>%
    tidyr::pivot_wider(
      names_from = persistence_stage,
      values_from = n
    ) %>%
    mutate(
      invalid_rate = !is.na(first_year) &
        !is.na(second_year) &
        second_year > first_year,
      category = "Persistence",
      Group = persistence_group,
      n = if_else(first_year > 0 & !invalid_rate, second_year / first_year, NA_real_)
    ) %>%
    select(
      district,
      source_file,
      effective_date,
      category,
      Group,
      class_year,
      n,
      first_year,
      second_year
    )

  invalid_rows <- rates %>%
    filter(!is.na(first_year), !is.na(second_year), second_year > first_year)

  if (nrow(invalid_rows) > 0) {
    warning(sprintf(
      "Blanking %s persistence rates where second-year count exceeds first-year count",
      nrow(invalid_rows)
    ))
  }

  rates
}

write_output <- function(df, path) {
  utils::write.csv(df, path, row.names = FALSE, na = "")
}

empty_summary <- tibble(
  district = character(),
  source_file = character(),
  effective_date = character(),
  category = character(),
  Group = character(),
  class_year = character(),
  n = numeric(),
  row_order = integer(),
  persistence_group = character(),
  persistence_stage = character()
)

empty_progress <- tibble(
  district = character(),
  source_file = character(),
  class_year = character(),
  total_in_class = numeric(),
  academic_year = character(),
  Group = character(),
  n = numeric(),
  row_order = integer()
)

empty_mci <- tibble(
  district = character(),
  source_file = character(),
  Name = character(),
  Rank = numeric(),
  State = character(),
  Level = character(),
  Type = character(),
  Total = numeric()
)

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

files <- list.files(input_dir, pattern = "xls$", full.names = TRUE)
if (length(files) == 0) {
  stop(sprintf("No .xls files found in %s", input_dir))
}

parsed <- files %>%
  set_names(basename(.)) %>%
  map(parse_workbook)

district_summary <- bind_rows(empty_summary, bind_rows(map(parsed, "summary"))) %>%
  apply_summary_maturity() %>%
  validate_summary_counts() %>%
  arrange(district, category, Group, class_year)

district_progress <- bind_rows(empty_progress, bind_rows(map(parsed, "progress"))) %>%
  apply_progress_maturity() %>%
  arrange(district, class_year, academic_year, Group)

district_mci <- bind_rows(empty_mci, bind_rows(map(parsed, "mci"))) %>%
  arrange(district, Rank, Name)

district_persistence <- build_persistence_rates(district_summary) %>%
  arrange(district, class_year, Group)

county_summary <- district_summary %>%
  filter(category != "Returned for second year") %>%
  group_by(category, Group, class_year) %>%
  summarise(n = sum_or_na(n), .groups = "drop") %>%
  arrange(category, Group, class_year)

county_progress <- district_progress %>%
  group_by(class_year, academic_year, Group) %>%
  summarise(n = sum_or_na(n), .groups = "drop") %>%
  arrange(class_year, academic_year, Group)

county_persistence <- district_summary %>%
  group_by(class_year, persistence_group, persistence_stage) %>%
  summarise(n = sum_or_na(n), .groups = "drop") %>%
  filter(!is.na(persistence_group)) %>%
  tidyr::pivot_wider(names_from = persistence_stage, values_from = n) %>%
  mutate(
    invalid_rate = !is.na(first_year) &
      !is.na(second_year) &
      second_year > first_year,
    category = "Persistence",
    Group = persistence_group,
    n = if_else(first_year > 0 & !invalid_rate, second_year / first_year, NA_real_)
  ) %>%
  select(category, Group, class_year, n, first_year, second_year) %>%
  arrange(class_year, Group)

county_mci <- district_mci %>%
  group_by(Name, State, Level, Type) %>%
  summarise(
    Total = sum(Total, na.rm = TRUE),
    district_count = n_distinct(district),
    .groups = "drop"
  ) %>%
  arrange(desc(Total), Name, State, Level, Type) %>%
  mutate(Rank = row_number()) %>%
  select(Name, Rank, State, Level, Type, Total, district_count)

run_summary <- tibble(
  metric = c(
    "district_files",
    "district_summary_rows",
    "district_progress_rows",
    "district_mci_rows",
    "county_summary_rows",
    "county_progress_rows",
    "county_mci_rows",
    "district_persistence_rows",
    "county_persistence_rows"
  ),
  value = c(
    length(files),
    nrow(district_summary),
    nrow(district_progress),
    nrow(district_mci),
    nrow(county_summary),
    nrow(county_progress),
    nrow(county_mci),
    nrow(district_persistence),
    nrow(county_persistence)
  )
)

write_output(district_summary, file.path(output_dir, "all_sheet_district_metrics.csv"))
write_output(county_summary, file.path(output_dir, "all_sheet_county_metrics.csv"))
write_output(district_progress, file.path(output_dir, "all_sheet_progress_district_metrics.csv"))
write_output(county_progress, file.path(output_dir, "all_sheet_progress_county_metrics.csv"))
write_output(district_persistence, file.path(output_dir, "all_sheet_persistence_district_metrics.csv"))
write_output(county_persistence, file.path(output_dir, "all_sheet_persistence_county_metrics.csv"))
write_output(district_mci, file.path(output_dir, "mci_district_candidates.csv"))
write_output(county_mci, file.path(output_dir, "mci_county_candidates.csv"))
write_output(run_summary, file.path(output_dir, "parse_summary.csv"))

message(sprintf("Parsed %s districtwide BASIC workbooks from %s", length(files), input_dir))
message(sprintf("Wrote outputs to %s", output_dir))
