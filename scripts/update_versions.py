#!/usr/bin/env python3
"""
Update ToonRepo.xml app versions to match each app's latest release.

For every <app> entry in ToonRepo.xml, this looks up the corresponding
ToonSoftwareCollective/<folder> repository, reads its version.txt at the
repo's default branch, and updates <version> in place if it differs.

Only touches ToonRepo.xml on the branch it's run against (intended for
`main`). The `test` and `dev` branches/manifests are maintained by hand
and are never read or written by this script.

Preserves the file's existing formatting: only the text inside the
<version>...</version> tag of a changed app is replaced, nothing else
is reformatted.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

ORG = "ToonSoftwareCollective"
REPO_FILE = os.path.join(os.path.dirname(__file__), "..", "ToonRepo.xml")
API_ROOT = "https://api.github.com"

APP_BLOCK_RE = re.compile(r"<app>.*?</app>", re.S)
NAME_RE = re.compile(r"<name>(.*?)</name>", re.S)
VERSION_RE = re.compile(r"(<version>)(.*?)(</version>)", re.S)
FOLDER_RE = re.compile(r"<folder>(.*?)</folder>", re.S)


def gh_request(path):
    """GET a GitHub API path, returning parsed JSON or None on 404."""
    token = os.environ.get("GITHUB_TOKEN")
    req = urllib.request.Request(API_ROOT + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def latest_version(folder):
    """Return the stripped contents of version.txt at folder's default
    branch, or None if the repo or file doesn't exist."""
    repo_info = gh_request(f"/repos/{ORG}/{folder}")
    if repo_info is None:
        print(f"  [{folder}] repo not found, skipping")
        return None
    default_branch = repo_info.get("default_branch", "main")

    contents = gh_request(
        f"/repos/{ORG}/{folder}/contents/version.txt?ref={default_branch}"
    )
    if contents is None:
        print(f"  [{folder}] no version.txt on '{default_branch}', skipping")
        return None

    import base64

    try:
        raw = base64.b64decode(contents["content"]).decode("utf-8")
    except Exception as e:  # pragma: no cover - defensive
        print(f"  [{folder}] could not decode version.txt: {e}")
        return None

    version = raw.strip()
    if not version:
        print(f"  [{folder}] version.txt is empty, skipping")
        return None
    return version


def main():
    with open(REPO_FILE, encoding="utf-8") as f:
        text = f.read()

    changes = []

    def process_block(match):
        block = match.group(0)
        name_m = NAME_RE.search(block)
        version_m = VERSION_RE.search(block)
        folder_m = FOLDER_RE.search(block)
        if not (name_m and version_m and folder_m):
            return block  # malformed entry, leave untouched

        name = name_m.group(1).strip()
        current_version = version_m.group(2).strip()
        folder = folder_m.group(1).strip()

        print(f"Checking {name} ({folder})...")
        new_version = latest_version(folder)
        if new_version is None or new_version == current_version:
            return block

        changes.append((name, folder, current_version, new_version))
        print(f"  [{folder}] {current_version} -> {new_version}")

        # Replace only the text between the version tags, keep the tags
        # and all surrounding whitespace/formatting exactly as they were.
        start, end = version_m.span(2)
        return block[:start] + new_version + block[end:]

    new_text = APP_BLOCK_RE.sub(process_block, text)

    if not changes:
        print("\nNo version changes.")
        return

    with open(REPO_FILE, "w", encoding="utf-8") as f:
        f.write(new_text)

    print(f"\n{len(changes)} app(s) updated:")
    for name, folder, old, new in changes:
        print(f"  - {name} ({folder}): {old} -> {new}")

    # Emit a summary for the workflow to use in the commit message / PR body.
    summary_path = os.environ.get("CHANGES_SUMMARY_FILE")
    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as f:
            for name, folder, old, new in changes:
                f.write(f"- {name} ({folder}): {old} -> {new}\n")


if __name__ == "__main__":
    sys.exit(main())
