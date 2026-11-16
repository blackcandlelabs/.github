# blackcandlelabs/.github

This repository holds the Black Candle Labs organization profile
(`profile/README.md`, shown on https://github.com/blackcandlelabs) and the
automation that keeps its stats current.

## How the stats work

`.github/workflows/update-stats.yml` runs `scripts/update_stats.py` every
6 hours (and on demand from the Actions tab). The script pulls live data
from the GitHub API across black-candle-technologies, blackcandlelabs, and
Black-Candle-Administration: repository counts, commits on default
branches, open and merged pull requests, open issues, stars, and lines of
code counted with tokei over shallow clones.

It needs one repository secret:

- `STATS_TOKEN`: a GitHub classic personal access token with the `repo`
  scope, owned by an account that can read every repository in the three
  organizations. Without it the private repositories are invisible and the
  job fails on purpose rather than publish partial numbers.

Forks are excluded from commit and line counts (they carry upstream
history and code). Repositories with names starting with `DELETE-ME` are
excluded everywhere.
