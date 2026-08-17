#!/usr/bin/env python3
"""抓取雀魂前端页面与主 JS，搜索协议关键逻辑（调研用）。"""
import json
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://game.maj-soul.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "page"
    if action == "page":
        html = get("https://game.maj-soul.com/1/").decode("utf-8", errors="replace")
        print("HTML len:", len(html))
        for m in re.finditer(r'(?:src|href)="([^"]+\.(?:js|css)[^"]*)"', html):
            print("  asset:", m.group(1))
        open(r"C:\dsh-temp\dsh-SB9OWS\majsoul_index.html", "w", encoding="utf-8").write(html)
    elif action == "js":
        url = sys.argv[2]
        data = get(url)
        out = r"C:\dsh-temp\dsh-SB9OWS\majsoul_main.js"
        open(out, "wb").write(data)
        print("saved", out, len(data), "bytes")
    elif action == "config":
        for host in ["https://www.majsoul.com", "https://game.maj-soul.com"]:
            try:
                v = json.loads(get(host + "/1/version.json"))
                print(host, "version:", v.get("version"))
                cfg = json.loads(get(f"{host}/1/v{v['version']}/config.json"))
                print("  ip:", json.dumps(cfg.get("ip"), ensure_ascii=False)[:1600])
            except Exception as e:
                print(host, "ERR", type(e).__name__, str(e)[:100])
    elif action == "grep":
        text = open(r"C:\dsh-temp\dsh-SB9OWS\majsoul_main.js", encoding="utf-8", errors="replace").read()
        pat = sys.argv[2]
        for m in re.finditer(pat, text):
            s = max(0, m.start() - 150)
            print("...", text[s:m.end() + 150].replace("\n", " ")[:330], "...")
            print("---")


if __name__ == "__main__":
    main()
