#!/usr/bin/env python3
"""Validate interactive fiction turns on GitHub Issues."""

import json
import os
import urllib.request

CHAR_LIMIT = 500
STORY_LABEL = "interactive-fiction"
BOT_LOGIN = "github-actions[bot]"


def api(method, url, data=None):
    token = os.environ["GITHUB_TOKEN"]
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        if resp.status == 204:
            return None
        return json.loads(resp.read().decode())


def graphql(query, variables=None):
    token = os.environ["GITHUB_TOKEN"]
    data = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=data, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def react(comment_id, reaction):
    repo = os.environ["GITHUB_REPOSITORY"]
    api("POST",
        f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}/reactions",
        {"content": reaction})


def post_comment(issue_number, body):
    repo = os.environ["GITHUB_REPOSITORY"]
    api("POST",
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        {"body": body})


def minimize(node_id):
    graphql("""
        mutation($id: ID!) {
            minimizeComment(input: {subjectId: $id, classifier: OFF_TOPIC}) {
                minimizedComment { isMinimized }
            }
        }
    """, {"id": node_id})


def reject(issue_number, comment_id, node_id, message):
    react(comment_id, "-1")
    minimize(node_id)
    post_comment(issue_number, message)


def find_last_valid_author(issue_number, issue_author):
    """Find the author of the last valid story turn by scanning bot replies."""
    repo = os.environ["GITHUB_REPOSITORY"]
    comments = api("GET",
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        f"?per_page=100&direction=desc")

    for c in comments:
        if c["user"]["login"] == BOT_LOGIN and "<!-- STORY_TURN:" in c["body"]:
            body = c["body"]
            start = body.index("<!-- STORY_TURN:") + len("<!-- STORY_TURN:")
            end = body.index(" -->", start)
            return body[start:end]

    # No valid turns yet — the issue author (story opener) had the last turn
    return issue_author


def main():
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        event = json.load(f)

    issue = event["issue"]
    comment_data = event["comment"]

    issue_number = issue["number"]
    issue_author = issue["user"]["login"]
    labels = [l["name"] for l in issue["labels"]]

    comment_id = comment_data["id"]
    node_id = comment_data["node_id"]
    author = comment_data["user"]["login"]
    body = comment_data["body"].strip()

    if STORY_LABEL not in labels:
        return

    if author == BOT_LOGIN:
        return

    if not body:
        reject(issue_number, comment_id, node_id,
               f"❌ **Turn rejected** — @{author}, empty turns aren't allowed. "
               f"Write something!")
        return

    if len(body) > CHAR_LIMIT:
        reject(issue_number, comment_id, node_id,
               f"❌ **Turn rejected** — @{author}, your entry is **{len(body)}** characters. "
               f"The limit is **{CHAR_LIMIT}**. Trim it down and try again!")
        return

    last_author = find_last_valid_author(issue_number, issue_author)
    if author == last_author:
        reject(issue_number, comment_id, node_id,
               f"❌ **Turn rejected** — @{author}, you can't take two turns in a row. "
               f"Wait for someone else to continue the story!")
        return

    react(comment_id, "+1")
    post_comment(issue_number,
                 f"<!-- STORY_TURN:{author} -->\n"
                 f"✅ **Turn accepted!** @{author} continues the story. "
                 f"({len(body)}/{CHAR_LIMIT} characters)\n\n"
                 f"*Who's next?*")


if __name__ == "__main__":
    main()
