#!/usr/bin/env python3
"""Summarize recent public-repo commits via Claude Haiku and write NOW.md.

Runs nightly in GitHub Actions. Consumed by wshoffner.dev's now.working
panel, which fetches NOW.md from raw.githubusercontent.com at build time
with hourly ISR revalidation.

Only public repos are scanned. The GitHub API naturally excludes private
repos for unauthenticated or token-scoped requests, but we also filter
defensively on `private`, `fork`, and `archived`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

GITHUB_USER = "TickTockBent"
DAYS_BACK = 14
MAX_REPOS = 15
MAX_COMMITS_PER_REPO = 5
MAX_COMMITS_TOTAL = 12
OUTPUT_PATH = "NOW.md"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Repos to skip even if they match the public filter (e.g. the profile repo itself).
SKIP_REPOS = {"ticktockbent"}


def gh(path: str) -> dict | list:
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "now-working-refresher",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def list_public_repos() -> list[str]:
    repos = gh(f"/users/{GITHUB_USER}/repos?type=public&sort=pushed&per_page=100")
    out: list[str] = []
    for r in repos:
        if r.get("fork") or r.get("archived") or r.get("private"):
            continue
        name = r["name"]
        if name.lower() in SKIP_REPOS:
            continue
        out.append(name)
    return out[:MAX_REPOS]


NOISE_PREFIXES = (
    "merge pull request",
    "merge branch",
    "merge remote-tracking",
    "bump ",
    "update dependency ",
    "chore(deps):",
    "build(deps):",
)


def is_noise(msg: str) -> bool:
    m = msg.lower().lstrip()
    return m.startswith(NOISE_PREFIXES)


def recent_commits(repo: str) -> list[dict]:
    # Over-fetch so we can drop noise (merges, dependabot bumps) and still have
    # enough meaningful commits to surface.
    fetch_per_repo = MAX_COMMITS_PER_REPO * 4
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        commits = gh(
            f"/repos/{GITHUB_USER}/{repo}/commits"
            f"?since={since}&per_page={fetch_per_repo}&author={GITHUB_USER}"
        )
    except urllib.error.HTTPError as e:
        print(f"  skip {repo}: {e.code}")
        return []
    except Exception as e:
        print(f"  skip {repo}: {e}")
        return []

    out = []
    for c in commits:
        author = (c.get("author") or {}).get("login", "") or ""
        if author.lower() in {"dependabot[bot]", "github-actions[bot]"}:
            continue
        msg = c["commit"]["message"].split("\n", 1)[0][:120]
        if is_noise(msg):
            continue
        out.append(
            {
                "repo": repo,
                "sha": c["sha"][:7],
                "msg": msg,
                "date": c["commit"]["author"]["date"],
            }
        )
        if len(out) >= MAX_COMMITS_PER_REPO:
            break
    return out


def humanize_ago(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "now"
    if hours < 24:
        return f"{int(hours)}h"
    days = int(hours // 24)
    if days == 1:
        return "1d"
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    return f"{weeks}w"


def tag_for(msg: str) -> str:
    m = msg.lower()
    if any(x in m for x in ("wip", "scaffold", "draft", "experiment")):
        return "m"
    if any(x in m for x in ("fix", "bug", "patch", "hotfix")):
        return "c"
    return "g"


def summarize(commits: list[dict]) -> str:
    if not ANTHROPIC_API_KEY or not commits:
        return "Building things, breaking things, occasionally shipping them."

    commit_lines = "\n".join(
        f"- {c['repo']}: {c['msg']}" for c in commits[:20]
    )
    prompt = (
        "Given these recent public git commits, write ONE concise sentence "
        "(max 140 characters) describing what the developer is currently "
        "working on. Casual but technical tone. Third person, present tense. "
        "No quotes, no prefixes like 'Summary:'. Just the sentence.\n\n"
        f"{commit_lines}"
    )
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"anthropic api error: {e.code} {e.read().decode()[:200]}")
        return "Building things, breaking things, occasionally shipping them."

    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()
    return text.replace("\n", " ")[:160] or (
        "Building things, breaking things, occasionally shipping them."
    )


def write_now_md(summary: str, commits: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"updatedAt: {now}",
        f"summary: {json.dumps(summary)}",
        "commits:",
    ]
    for c in commits:
        entry = (
            f"  - {{ repo: {json.dumps(c['repo'])}, "
            f"sha: {json.dumps(c['sha'])}, "
            f"msg: {json.dumps(c['msg'])}, "
            f"ts: {json.dumps(c['ts'])}, "
            f"tag: {c['tag']} }}"
        )
        lines.append(entry)
    lines += ["---", ""]
    lines += [
        "## now.working",
        "",
        "_Auto-updated nightly. Public-repo commits only. "
        "Rendered on [wshoffner.dev](https://www.wshoffner.dev) in the now.working panel._",
        "",
        f"**Right now:** {summary}",
        "",
        "| Repo | Commit | Message | When |",
        "|---|---|---|---|",
    ]
    for c in commits:
        lines.append(
            f"| {c['repo']} | `{c['sha']}` | {c['msg']} | {c['ts']} |"
        )
    lines.append("")
    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {OUTPUT_PATH} ({len(commits)} commits).")


def main() -> None:
    print(f"Listing public repos for {GITHUB_USER}...")
    repos = list_public_repos()
    print(f"  {len(repos)} repos: {', '.join(repos)}")

    print("Collecting recent commits...")
    all_commits: list[dict] = []
    for r in repos:
        all_commits.extend(recent_commits(r))
    all_commits.sort(key=lambda c: c["date"], reverse=True)

    print(f"  {len(all_commits)} commits in last {DAYS_BACK} days")

    print("Summarizing via Claude Haiku...")
    summary = summarize(all_commits)
    print(f"  summary: {summary}")

    display = [
        {
            "repo": c["repo"],
            "sha": c["sha"],
            "msg": c["msg"],
            "ts": humanize_ago(c["date"]),
            "tag": tag_for(c["msg"]),
        }
        for c in all_commits[:MAX_COMMITS_TOTAL]
    ]
    write_now_md(summary, display)


if __name__ == "__main__":
    main()
