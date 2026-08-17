#!/usr/bin/env python3
"""Fetch a raw file from a GitHub repo via API and print it.
Usage: gh_file.py owner/repo path [outfile]
"""
import base64
import json
import os
import sys
import urllib.request


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-dev"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    repo, path = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else None
    d = get(f"https://api.github.com/repos/{repo}/contents/{path}")
    data = base64.b64decode(d["content"])
    if out:
        with open(out, "wb") as f:
            f.write(data)
        print(f"OK {repo}/{path} -> {out} ({len(data)} bytes)")
    else:
        sys.stdout.write(data.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
