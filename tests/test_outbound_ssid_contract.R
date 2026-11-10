# REQ-22 / DEC-19: test actual outbound field expressions without executing pipelines.
# All identifiers are synthetic, including the leading-zero boundary case.
generators <- c("01-process.R", "01d-processAVID.R", "01g-processAlvord.R",
                "01t-processTVUSD.R", "01u-processMVUSD.R")
fixture <- c("0000000001", "1234567890")
find_field <- function(expression, field) {
  if (!is.call(expression) && !is.expression(expression)) return(list())
  if (is.call(expression) && identical(expression[[1]], as.name("transmute"))) {
    args <- as.list(expression)[-1]
    if (field %in% names(args) && "SSID" %in% all.names(args[[field]])) {
      return(list(args[[field]]))
    }
  }
  unlist(lapply(as.list(expression), find_field, field = field), recursive = FALSE)
}
for (path in generators) {
  field <- if (path == "01-process.R") "J" else "L"
  expressions <- find_field(parse(path), field)
  stopifnot(length(expressions) == 1L)
  outbound <- eval(expressions[[1]], envir = list(SSID = fixture))
  stopifnot(identical(outbound, fixture))
  text <- textConnection("serialized", "w", local = TRUE)
  write.table(data.frame(SSID = outbound), text, sep = "\t", quote = FALSE,
              row.names = FALSE, col.names = FALSE)
  close(text)
  parsed <- read.table(text = serialized, sep = "\t", header = FALSE,
                       colClasses = "character")[[1]]
  stopifnot(identical(parsed, fixture), !any(grepl("_", parsed, fixed = TRUE)))
}
cat("Raw outbound SSID contract passed for all five generators\n")
