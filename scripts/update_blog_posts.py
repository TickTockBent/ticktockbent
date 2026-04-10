#!/usr/bin/env python3
"""Fetch latest blog posts from dev.to and update README.md."""

import json
import re
import urllib.request

DEVTO_USER = "ticktockbent"
POST_COUNT = 5
README_PATH = "README.md"
START_MARKER = "<!-- BLOG-POSTS:START -->"
END_MARKER = "<!-- BLOG-POSTS:END -->"
MAX_DESC_LEN = 120


def fetch_posts():
    url = f"https://dev.to/api/articles?username={DEVTO_USER}&per_page={POST_COUNT}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "github-profile-readme-updater",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def truncate(text, length):
    if len(text) <= length:
        return text
    return text[:length - 3].rsplit(" ", 1)[0] + "..."


def build_table(posts):
    lines = [
        START_MARKER,
        "<!-- This section is auto-updated nightly by a GitHub Action -->",
        "| Post | Description |",
        "|---|---|",
    ]
    for post in posts:
        title = post["title"]
        url = post.get("canonical_url") or post["url"]
        description = truncate(post.get("description", ""), MAX_DESC_LEN)
        lines.append(f"| [{title}]({url}) | {description} |")
    lines.append(END_MARKER)
    return "\n".join(lines)


def main():
    posts = fetch_posts()
    table = build_table(posts)

    with open(README_PATH, "r") as f:
        readme = f.read()

    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )

    if not pattern.search(readme):
        print("ERROR: Could not find blog post markers in README.md")
        raise SystemExit(1)

    updated = pattern.sub(table, readme)

    if updated == readme:
        print("No changes needed.")
        return

    with open(README_PATH, "w") as f:
        f.write(updated)

    print(f"Updated README with {len(posts)} posts.")


if __name__ == "__main__":
    main()
