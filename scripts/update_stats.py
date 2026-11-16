#!/usr/bin/env python3
"""Regenerate the stats block in profile/README.md from live GitHub data.

Covers three organizations: black-candle-technologies, blackcandlelabs,
Black-Candle-Administration.

Stats collected:
  - repository counts (all repos, per org and total)
  - total commits on default branches (GraphQL history totalCount)
  - pull requests open / merged and open issues (Search API)
  - total stars
  - lines of code via tokei over shallow clones

Forks are excluded from commit and line counts because they carry upstream
history and code. Repositories whose names start with DELETE-ME are excluded
from everything.

Requires:
  STATS_TOKEN  a GitHub token that can read every repository in the three
               orgs (a classic PAT with the `repo` scope works). Without it,
               private repositories are invisible and the numbers would be
               wrong, so the script refuses to run.
  TOKEI        path to a tokei binary (default: "tokei" on PATH). If tokei
               is unavailable, the previous lines-of-code value is kept.

Run from the repository root:  python3 scripts/update_stats.py
Exit code 0 whether or not the README changed; prints what it did.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ORGS = ["black-candle-technologies", "blackcandlelabs", "Black-Candle-Administration"]
README_PATH = os.path.join(os.path.dirname(__file__), "..", "profile", "README.md")
START = "<!-- BCT-STATS:START -->"
END = "<!-- BCT-STATS:END -->"
API = "https://api.github.com"
TOKEN = os.environ.get("STATS_TOKEN", "")


def api(method, path, body=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def list_repos(org):
    repos, page = [], 1
    while True:
        batch = api("GET", f"/orgs/{org}/repos?per_page=100&page={page}")
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def excluded(name):
    return name.startswith("DELETE-ME")


def commit_counts(repos):
    """repos: list of (org, name). Returns {(org, name): int} via GraphQL."""
    counts = {}
    for i in range(0, len(repos), 25):
        chunk = repos[i:i + 25]
        parts, keys = [], []
        for j, (org, name) in enumerate(chunk):
            a = f"r{j}"
            keys.append((a, (org, name)))
            parts.append(
                f'{a}: repository(owner:"{org}", name:"{name}") '
                "{ defaultBranchRef { target { ... on Commit { history { totalCount } } } } }"
            )
        res = api("POST", "/graphql", {"query": "query { " + " ".join(parts) + " }"})
        data = res.get("data") or {}
        for a, key in keys:
            node = data.get(a) or {}
            ref = node.get("defaultBranchRef") or {}
            target = ref.get("target") or {}
            history = target.get("history") or {}
            counts[key] = history.get("totalCount", 0)
    return counts


def search_count(query):
    enc = urllib.parse.quote(query)
    return api("GET", f"/search/issues?q={enc}&per_page=1")["total_count"]


def count_lines(repos):
    """Shallow-clone each repo and count code lines with tokei.

    Returns (total_code_lines, {language: lines}, repos_counted) or None
    when tokei is not available.
    """
    tokei = os.environ.get("TOKEI", "tokei")
    try:
        subprocess.run([tokei, "--version"], capture_output=True, check=True)
    except Exception:
        return None
    total, languages, counted = 0, {}, 0
    with tempfile.TemporaryDirectory() as tmp:
        for idx, (org, name) in enumerate(repos):
            dest = os.path.join(tmp, f"r{idx}")
            url = f"https://x-access-token:{TOKEN}@github.com/{org}/{name}.git"
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", "--single-branch", "--quiet", url, dest],
                capture_output=True, timeout=900,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            if clone.returncode != 0 or not os.path.isdir(dest):
                continue
            out = subprocess.run([tokei, "--output", "json", dest],
                                 capture_output=True, text=True, timeout=600)
            try:
                report = json.loads(out.stdout)
            except Exception:
                continue
            counted += 1
            for lang, vals in report.items():
                if lang == "Total":
                    continue
                code = vals.get("code", 0)
                if code:
                    languages[lang] = languages.get(lang, 0) + code
                    total += code
    return total, languages, counted


def fmt(n):
    return f"{n:,}"


def render(stats, loc, prev_loc, counted_repos, total_repos):
    now = datetime.now(ZoneInfo("America/Chicago"))
    stamp = now.strftime("%b %-d, %Y, %-I:%M %p CT")
    if loc is not None:
        loc_value = fmt(loc[0])
    elif prev_loc:
        loc_value = prev_loc
    else:
        loc_value = "—"
    lines = []
    lines.append("## Black Candle by the numbers")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Repositories** | {stats['repos_total']} across 3 organizations |")
    lines.append(f"| **Total commits** | {fmt(stats['commits_total'])} |")
    lines.append(f"| **Lines of code** | {loc_value} |")
    lines.append(f"| **Pull requests** | {stats['prs_open']} open · {fmt(stats['prs_merged'])} merged |")
    lines.append(f"| **Open issues** | {fmt(stats['issues_open'])} |")
    lines.append(f"| **Stars** | {fmt(stats['stars'])} |")
    lines.append("")
    lines.append("### Per organization")
    lines.append("")
    lines.append("| Organization | Repos | Commits | PRs open | PRs merged |")
    lines.append("|---|---|---|---|---|")
    for org in ORGS:
        s = stats["per_org"][org]
        lines.append(
            f"| [{org}](https://github.com/{org}) | {s['repos']} | {fmt(s['commits'])} "
            f"| {s['prs_open']} | {fmt(s['prs_merged'])} |"
        )
    if loc is not None and loc[1]:
        top = sorted(loc[1].items(), key=lambda kv: kv[1], reverse=True)[:8]
        lines.append("")
        lines.append("### Top languages (lines of code)")
        lines.append("")
        lines.append("| Language | Lines |")
        lines.append("|---|---|")
        for lang, n in top:
            lines.append(f"| {lang} | {fmt(n)} |")
    lines.append("")
    lines.append(
        "<sub>Updated automatically every 6 hours by the update-stats workflow in this "
        f"repository. Last update: {stamp}. Commits are counted on each repository's "
        "default branch. Lines of code are counted with tokei across non-fork "
        f"repositories ({counted_repos} of {total_repos} repositories counted; forks "
        "carry upstream history and code, so they are excluded from commit and line "
        "counts). Repositories with names starting with DELETE-ME are excluded "
        "everywhere.</sub>"
    )
    return "\n".join(lines)


def main():
    if not TOKEN:
        print("STATS_TOKEN is not set; refusing to publish partial stats.", file=sys.stderr)
        return 1
    all_repos = {}
    for org in ORGS:
        all_repos[org] = [r for r in list_repos(org) if not excluded(r["name"])]
    counted = [
        (org, r["name"])
        for org in ORGS
        for r in all_repos[org]
        if not r.get("fork")
    ]
    commits = commit_counts(counted)
    per_org = {}
    for org in ORGS:
        org_repos = all_repos[org]
        per_org[org] = {
            "repos": len(org_repos),
            "commits": sum(commits.get((org, r["name"]), 0) for r in org_repos if not r.get("fork")),
            "prs_open": search_count(f"org:{org} type:pr is:open"),
            "prs_merged": search_count(f"org:{org} type:pr is:merged"),
            "issues_open": search_count(f"org:{org} type:issue is:open"),
            "stars": sum(r["stargazers_count"] for r in org_repos),
        }
    stats = {
        "repos_total": sum(s["repos"] for s in per_org.values()),
        "commits_total": sum(s["commits"] for s in per_org.values()),
        "prs_open": sum(s["prs_open"] for s in per_org.values()),
        "prs_merged": sum(s["prs_merged"] for s in per_org.values()),
        "issues_open": sum(s["issues_open"] for s in per_org.values()),
        "stars": sum(s["stars"] for s in per_org.values()),
        "per_org": per_org,
    }
    loc = count_lines(counted)
    with open(README_PATH) as f:
        text = f.read()
    m = re.search(re.escape(START) + r"(.*?)" + re.escape(END), text, re.S)
    if not m:
        print("Stats markers not found in README.", file=sys.stderr)
        return 1
    prev = re.search(r"\| \*\*Lines of code\*\* \| ([^|]+) \|", m.group(1))
    prev_loc = prev.group(1).strip() if prev else None
    block = render(stats, loc, prev_loc, len(counted), stats["repos_total"])
    new_text = text[:m.start()] + START + "\n" + block + "\n" + END + text[m.end():]
    if new_text != text:
        with open(README_PATH, "w") as f:
            f.write(new_text)
        print("README stats updated.")
    else:
        print("README already up to date.")
    print(json.dumps({k: v for k, v in stats.items() if k != "per_org"}, indent=2))
    if loc:
        print(f"Lines of code: {loc[0]:,} across {loc[2]} cloned repos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
