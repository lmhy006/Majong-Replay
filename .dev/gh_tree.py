#!/usr/bin/env python3
"""Query GitHub repo tree via API and print matching paths."""
import json
import sys
import urllib.request


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-dev"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    repo = sys.argv[1]
    keywords = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    info = get(f"https://api.github.com/repos/{repo}")
    branch = info.get("default_branch")
    print(f"== {repo} | default branch: {branch} | {info.get('description')}")
    tree = get(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1")
    paths = [t["path"] for t in tree.get("tree", [])]
    print(f"entries: {len(paths)}")
    for p in paths:
        lp = p.lower()
        if not keywords or any(k.lower() in lp for k in keywords):
            print("  ", p)


if __name__ == "__main__":
    main()
