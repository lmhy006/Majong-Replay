#!/usr/bin/env python3
"""Download a GitHub repo zip to the temp dir. Usage: gh_dl.py owner/repo [outname]"""
import json
import os
import sys
import urllib.request

TMP = r"C:\dsh-temp\dsh-SB9OWS"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-dev"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    repo = sys.argv[1]
    outname = sys.argv[2] if len(sys.argv) > 2 else repo.split("/")[1]
    info = get(f"https://api.github.com/repos/{repo}")
    branch = info.get("default_branch")
    url = f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-dev"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    path = os.path.join(TMP, outname + ".zip")
    with open(path, "wb") as f:
        f.write(data)
    print(f"OK {repo} [{branch}] -> {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
