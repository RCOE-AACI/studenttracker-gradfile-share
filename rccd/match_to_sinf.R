# Match RCCD records to the roster/SINF using normalized identifiers and names; keep unresolved candidates in local audit outputs. REQ-16.
# Run from the project root. Sourcing this file may execute reads/writes immediately.
# Source paths and cohort dates describe the original project; review them before a new run.
library(arrow)
library(dplyr)
library(lubridate)
library(readr)
library(stringr)

normalize_name <- function(x) {
  x <- if_else(is.na(x) | x == "", NA_character_, x)
  x <- str_to_upper(x)
  x <- str_replace_all(x, "\\s+", " ")
  x <- str_trim(x)
  x <- str_replace_all(x, "[^A-Z ]", "")
  x <- str_replace_all(x, "\\s+", "")
  x <- na_if(x, "")
  x
}

submissionfiles_list <- function(roots = c("submissionfiles")) {
  roots <- roots[dir.exists(roots)]
  if (length(roots) == 0) return(character(0))
  files <- unlist(lapply(roots, function(root) {
    list.files(root, pattern = "\\.txt$", full.names = TRUE, recursive = TRUE)
  }))
  files <- files[!str_detect(basename(files), "^\\.")]
  sort(unique(files))
}

submissionfile_schoolyear <- function(path) {
  line <- readLines(path, n = 1, warn = FALSE)
  if (length(line) == 0) return(NA_character_)
  parts <- str_split(line[[1]], "\t", simplify = TRUE)
  if (ncol(parts) < 6) return(NA_character_)
  year <- parts[[1, 6]]
  year <- str_trim(year)
  if (year == "") return(NA_character_)
  year
}

roster_load_from_submissionfiles <- function(cohort_years, roots = c("submissionfiles")) {
  cohort_years <- as.integer(cohort_years)
  schoolyears <- sprintf("%s-%s", cohort_years - 1, cohort_years)

  files <- submissionfiles_list(roots)
  if (length(files) == 0) return(NULL)

  years <- vapply(files, submissionfile_schoolyear, character(1))
  keep <- files[years %in% schoolyears]
  if (length(keep) == 0) return(NULL)

  roster <- purrr::map_dfr(
    keep,
    ~ read_tsv(.x, col_names = FALSE, col_types = cols(.default = col_character()))
  ) %>%
    filter(.data[["X1"]] == "PD3") %>%
    transmute(
      SSID = str_remove(.data[["X10"]], "^_"),
      dob = ymd(.data[["X9"]]),
      legal_first = .data[["X3"]],
      legal_last = .data[["X5"]],
      alias_first = .data[["X7"]],
      alias_last = .data[["X8"]],
      preferred_first = NA_character_,
      preferred_last = NA_character_
    ) %>%
    filter(!is.na(.data[["SSID"]]), .data[["SSID"]] != "", !is.na(.data[["dob"]])) %>%
    distinct()

  roster
}

norm_levenshtein <- function(a, b) {
  a <- normalize_name(a)
  b <- normalize_name(b)

  as.numeric(mapply(
    function(x, y) {
      if (is.na(x) || is.na(y)) return(NA_real_)
      dist <- utils::adist(x, y)[1, 1]
      denom <- max(nchar(x), nchar(y))
      if (denom == 0) return(0)
      dist / denom
    },
    a,
    b,
    USE.NAMES = FALSE
  ))
}

name_distance <- function(a, b, jw_p = 0.1) {
  a <- normalize_name(a)
  b <- normalize_name(b)
  if (requireNamespace("stringdist", quietly = TRUE)) {
    return(stringdist::stringdist(a, b, method = "jw", p = jw_p))
  }
  norm_levenshtein(a, b)
}

sinf_load_relevant <- function(sinf_path = "data/cumulative_sinf.parquet", dob_values = NULL) {
  ds <- open_dataset(sinf_path)

  sinf_relevant <- ds %>%
    select(
      SSID = `SSID`,
      legal_first = `Student Legal First Name`,
      legal_middle = `Student Legal Middle Name`,
      legal_last = `Student Legal Last Name`,
      alias_first = `Student Alias First Name`,
      alias_middle = `Student Alias Middle Name`,
      alias_last = `Student Alias Last Name`,
      preferred_first = `Student Preferred First Name`,
      preferred_last = `Student Preferred Last Name`,
      dob_raw = `Student Birth Date`
    )

  if (!is.null(dob_values)) {
    dob_chars <- unique(c(format(dob_values, "%Y%m%d"), format(dob_values, "%Y-%m-%d")))
    sinf_relevant <- sinf_relevant %>% filter(.data[["dob_raw"]] %in% dob_chars)
  }

  sinf_relevant %>%
    collect() %>%
    transmute(
      SSID = SSID,
      legal_first = legal_first,
      legal_middle = legal_middle,
      legal_last = legal_last,
      alias_first = alias_first,
      alias_middle = alias_middle,
      alias_last = alias_last,
      preferred_first = preferred_first,
      preferred_last = preferred_last,
      dob = ymd(dob_raw)
    ) %>%
    distinct()
}

reference_load <- function(
    cohort_years,
    submission_roots = c("submissionfiles"),
    sinf_path = "data/cumulative_sinf.parquet",
    dob_values = NULL
) {
  roster <- roster_load_from_submissionfiles(cohort_years = cohort_years, roots = submission_roots)
  if (!is.null(roster) && nrow(roster) > 0) return(roster)
  sinf_load_relevant(sinf_path = sinf_path, dob_values = dob_values)
}

rccd_load_crosswalk <- function(path = "data/rccd_college_id_ssid_crosswalk.parquet") {
  if (!file.exists(path)) {
    return(tibble(
      `College Student ID` = character(),
      SSID = character(),
      match_source = character(),
      match_score = numeric(),
      first_term = character(),
      last_term = character(),
      updated_at = character()
    ))
  }
  read_parquet(path)
}

rccd_apply_crosswalk <- function(rccd_tbl, crosswalk_tbl) {
  has_ssid <- "SSID" %in% names(rccd_tbl)
  has_match_source <- "match_source" %in% names(rccd_tbl)
  rccd_base <- if (has_match_source) rccd_tbl else mutate(rccd_tbl, match_source = NA_character_)

  rccd_with_ssid <- rccd_base %>%
    left_join(
      crosswalk_tbl %>% select(`College Student ID`, SSID_crosswalk = SSID),
      by = "College Student ID"
    ) %>%
    mutate(
      SSID_original = if (has_ssid) .data[["SSID"]] else NA_character_,
      SSID = dplyr::coalesce(
        if (has_ssid) .data[["SSID"]] else NA_character_,
        .data[["SSID_crosswalk"]]
      ),
      match_source = case_when(
        !is.na(.data[["match_source"]]) ~ .data[["match_source"]],
        !is.na(.data[["SSID_original"]]) ~ "ingested",
        is.na(.data[["SSID_original"]]) & !is.na(.data[["SSID_crosswalk"]]) ~ "crosswalk",
        TRUE ~ NA_character_
      )
    ) %>%
    select(-SSID_crosswalk, -SSID_original)
  rccd_with_ssid
}

rccd_load_overrides <- function(overrides_path = "data/rccd_match_overrides.csv") {
  if (!file.exists(overrides_path)) return(NULL)
  overrides <- read_csv(overrides_path, col_types = cols(.default = col_character()))
  if (!all(c("College Student ID", "SSID") %in% names(overrides))) {
    stop("Overrides file must include columns: College Student ID, SSID")
  }
  overrides %>% select(`College Student ID`, SSID, dplyr::everything())
}

rccd_apply_overrides <- function(rccd_tbl, overrides_tbl) {
  if (is.null(overrides_tbl) || nrow(overrides_tbl) == 0) return(rccd_tbl)

  rccd_tbl %>%
    left_join(
      overrides_tbl %>%
        transmute(
          `College Student ID`,
          override_present = TRUE,
          SSID_override = na_if(SSID, "")
        ),
      by = "College Student ID"
    ) %>%
    mutate(
      SSID = case_when(
        !is.na(.data[["override_present"]]) & is.na(.data[["SSID_override"]]) ~ NA_character_,
        TRUE ~ coalesce(.data[["SSID_override"]], .data[["SSID"]])
      ),
      match_source = case_when(
        !is.na(.data[["override_present"]]) & is.na(.data[["SSID_override"]]) ~ "override_suppress",
        !is.na(.data[["SSID_override"]]) ~ "override",
        TRUE ~ .data[["match_source"]]
      )
    ) %>%
    select(-SSID_override, -override_present)
}

rccd_fuzzy_match_new_ids <- function(
    rccd_tbl,
    sinf_tbl,
    weights = c(first = 0.25, last = 0.75),
    accept = list(max_score = 0.20, min_margin = 0.03, max_first = 0.25, max_last = 0.22),
    max_candidates_per_id = 3,
    jw_p = 0.1
) {
  if (!("match_source" %in% names(rccd_tbl))) {
    rccd_tbl <- rccd_tbl %>% mutate(match_source = NA_character_)
  }
  if (!("match_score" %in% names(rccd_tbl))) {
    rccd_tbl <- rccd_tbl %>% mutate(match_score = NA_real_)
  }
  if (!("match_margin" %in% names(rccd_tbl))) {
    rccd_tbl <- rccd_tbl %>% mutate(match_margin = NA_real_)
  }
  rccd_tbl <- rccd_tbl %>%
    mutate(
      dob = ymd(.data[["Date of Birth"]])
    )

  target <- rccd_tbl %>%
    filter(is.na(.data[["SSID"]]) & !is.na(.data[["dob"]])) %>%
    select(
      `College Student ID`,
      rccd_first = `First Name`,
      rccd_last = `Last Name`,
      dob
    ) %>%
    distinct()

  if (nrow(target) == 0) {
    return(list(rccd = rccd_tbl, candidates = tibble()))
  }

  sinf_candidates <- sinf_tbl %>% filter(.data[["dob"]] %in% unique(target$dob))
  if (nrow(sinf_candidates) == 0) {
    rccd_tbl <- rccd_tbl %>% mutate(match_source = coalesce(.data[["match_source"]], "unmatched"))
    return(list(rccd = rccd_tbl, candidates = tibble()))
  }

  pairs_base <- target %>%
    inner_join(sinf_candidates, by = "dob") %>%
    mutate(
      rccd_first_norm = normalize_name(.data[["rccd_first"]]),
      rccd_last_norm = normalize_name(.data[["rccd_last"]]),
      legal_first_norm = normalize_name(.data[["legal_first"]]),
      legal_last_norm = normalize_name(.data[["legal_last"]]),
      alias_first_norm = normalize_name(.data[["alias_first"]]),
      alias_last_norm = normalize_name(.data[["alias_last"]]),
      preferred_first_norm = normalize_name(.data[["preferred_first"]]),
      preferred_last_norm = normalize_name(.data[["preferred_last"]]),
      rccd_first_i = str_sub(.data[["rccd_first_norm"]], 1, 1),
      rccd_last_i = str_sub(.data[["rccd_last_norm"]], 1, 1),
      legal_first_i = str_sub(.data[["legal_first_norm"]], 1, 1),
      legal_last_i = str_sub(.data[["legal_last_norm"]], 1, 1),
      alias_first_i = str_sub(.data[["alias_first_norm"]], 1, 1),
      alias_last_i = str_sub(.data[["alias_last_norm"]], 1, 1),
      preferred_first_i = str_sub(.data[["preferred_first_norm"]], 1, 1),
      preferred_last_i = str_sub(.data[["preferred_last_norm"]], 1, 1)
    )

  pairs_initial <- pairs_base %>%
    filter(
      is.na(.data[["rccd_first_i"]]) |
        .data[["rccd_first_i"]] == .data[["legal_first_i"]] |
        .data[["rccd_first_i"]] == .data[["alias_first_i"]] |
        .data[["rccd_first_i"]] == .data[["preferred_first_i"]],
      is.na(.data[["rccd_last_i"]]) |
        .data[["rccd_last_i"]] == .data[["legal_last_i"]] |
        .data[["rccd_last_i"]] == .data[["alias_last_i"]] |
        .data[["rccd_last_i"]] == .data[["preferred_last_i"]]
    )

  missing_ids <- target %>%
    select(`College Student ID`) %>%
    distinct() %>%
    anti_join(pairs_initial %>% select(`College Student ID`) %>% distinct(), by = "College Student ID")

  pairs <- bind_rows(
    pairs_initial,
    pairs_base %>% semi_join(missing_ids, by = "College Student ID")
  )

  pairs <- pairs %>%
    mutate(
      d_first_legal = name_distance(.data[["rccd_first"]], .data[["legal_first"]], jw_p = jw_p),
      d_first_alias = name_distance(.data[["rccd_first"]], .data[["alias_first"]], jw_p = jw_p),
      d_first_pref = name_distance(.data[["rccd_first"]], .data[["preferred_first"]], jw_p = jw_p),
      d_last_legal = name_distance(.data[["rccd_last"]], .data[["legal_last"]], jw_p = jw_p),
      d_last_alias = name_distance(.data[["rccd_last"]], .data[["alias_last"]], jw_p = jw_p),
      d_last_pref = name_distance(.data[["rccd_last"]], .data[["preferred_last"]], jw_p = jw_p),
      first_dist = pmin(d_first_legal, d_first_alias, d_first_pref, na.rm = TRUE),
      last_dist = pmin(d_last_legal, d_last_alias, d_last_pref, na.rm = TRUE),
      first_dist = coalesce(.data[["first_dist"]], 1),
      last_dist = coalesce(.data[["last_dist"]], 1),
      match_score = .data[["first_dist"]] * weights[["first"]] + .data[["last_dist"]] * weights[["last"]]
    ) %>%
    select(
      `College Student ID`,
      SSID,
      dob,
      match_score,
      first_dist,
      last_dist,
      rccd_first,
      rccd_last,
      legal_first,
      legal_last
    )

  ranked <- pairs %>%
    arrange(.data[["College Student ID"]], .data[["match_score"]]) %>%
    group_by(.data[["College Student ID"]]) %>%
    mutate(
      match_rank = row_number(),
      best_score = first(.data[["match_score"]]),
      second_best_score = dplyr::nth(.data[["match_score"]], 2),
      match_margin = .data[["second_best_score"]] - .data[["best_score"]]
    ) %>%
    ungroup()

  best <- ranked %>%
    filter(.data[["match_rank"]] == 1) %>%
    mutate(
      match_margin = coalesce(.data[["match_margin"]], Inf),
      accepted = (
        (.data[["best_score"]] <= accept[["max_score"]]) & (.data[["match_margin"]] >= accept[["min_margin"]])
      ) | (
        (.data[["first_dist"]] <= accept[["max_first"]]) & (.data[["last_dist"]] <= accept[["max_last"]])
      )
    ) %>%
    transmute(
      `College Student ID`,
      SSID_matched = if_else(.data[["accepted"]], .data[["SSID"]], NA_character_),
      match_score_best = .data[["best_score"]],
      match_margin_best = .data[["match_margin"]],
      match_source_best = if_else(.data[["accepted"]], "fuzzy", "ambiguous")
    )

  rccd_out <- rccd_tbl %>%
    left_join(best, by = "College Student ID") %>%
    mutate(
      SSID = coalesce(.data[["SSID"]], .data[["SSID_matched"]]),
      match_score = coalesce(.data[["match_score_best"]], .data[["match_score"]]),
      match_margin = coalesce(.data[["match_margin_best"]], .data[["match_margin"]]),
      match_source = coalesce(.data[["match_source"]], "unmatched"),
      match_source = if_else(!is.na(.data[["match_source_best"]]), .data[["match_source_best"]], .data[["match_source"]])
    ) %>%
    select(-SSID_matched, -match_score_best, -match_margin_best, -match_source_best)

  candidates_out <- ranked %>%
    filter(.data[["match_rank"]] <= max_candidates_per_id)

  list(rccd = rccd_out, candidates = candidates_out)
}

rccd_update_crosswalk <- function(rccd_tbl, crosswalk_tbl) {
  if (!("SSID" %in% names(rccd_tbl))) return(crosswalk_tbl)

  new_rows <- rccd_tbl %>%
    filter(
      !is.na(.data[["SSID"]]),
      .data[["match_source"]] %in% c("fuzzy", "override", "ingested")
    ) %>%
    group_by(.data[["College Student ID"]], .data[["SSID"]]) %>%
    summarise(
      match_source = dplyr::first(.data[["match_source"]]),
      match_score = suppressWarnings(min(.data[["match_score"]], na.rm = TRUE)),
      first_term = min(.data[["Academic Term"]], na.rm = TRUE),
      last_term = max(.data[["Academic Term"]], na.rm = TRUE),
      .groups = "drop"
    ) %>%
    mutate(
      match_score = if_else(is.infinite(.data[["match_score"]]), NA_real_, .data[["match_score"]]),
      updated_at = format(Sys.time(), tz = "UTC", usetz = TRUE)
    )

  existing_ids <- crosswalk_tbl %>% select(`College Student ID`) %>% distinct()
  new_rows <- new_rows %>% anti_join(existing_ids, by = "College Student ID")

  bind_rows(crosswalk_tbl, new_rows) %>%
    arrange(.data[["College Student ID"]])
}
