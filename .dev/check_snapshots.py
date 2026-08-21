#!/usr/bin/env python3
"""检查已保存的对局快照缓存（阶段三真实牌谱回归用）。

用法：
    python .dev/check_snapshots.py <uuid>
    python .dev/check_snapshots.py <path/to/snapshots.json>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "game_records"


def _fmt_player(p: dict) -> str:
    liqi = "立直" if (p.get("liqi") and p["liqi"].get("declared")) else "-"
    return (
        f"P{p['seat']}:手{len(p['hand'])} 河{len(p['discards'])} "
        f"副{len(p['melds'])} {p['score']} {liqi}"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python .dev/check_snapshots.py <uuid 或 JSON 文件路径>")
        return

    arg = sys.argv[1]
    path = Path(arg)
    if not path.exists():
        path = CACHE_DIR / f"{arg}.json"

    if not path.exists():
        print(f"找不到快照文件: {path}")
        print("请先通过 browser-fetch 拉取真实牌谱，或检查 data/game_records/ 目录。")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    snaps = data.get("snapshots", [])
    print(f"文件: {path}")
    print(f"uuid: {data.get('uuid', '-')}  快照数: {len(snaps)}\n")

    for s in snaps:
        print(
            f"[{s['step']:3d}] {s['event_type']:20s} "
            f"庄={s['dealer_seat']} 棒={s['liqibang']} 余={s['left_tile_count']} | "
            + " | ".join(_fmt_player(p) for p in s["players"])
        )


if __name__ == "__main__":
    main()
