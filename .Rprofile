suppressMessages(source("renv/activate.R"))
suppressMessages(bspm::enable()) # wrap it in suppressMessages() to avoid the initial message
options(repos = c(CRAN = sprintf("https://packagemanager.posit.co/cran/latest/bin/linux/noble-%s/%s", R.version["arch"], as.character(getRversion()[, 1:2]))))
options(repos = c(CRAN = "https://packagemanager.posit.co/all/latest"))

if (interactive()) {
  options(width = 120)
}
