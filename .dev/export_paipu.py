#!/usr/bin/env python3
"""从快照缓存导出 majiang-ui paipu JSON（阶段四调试用）。

用法：
    python .dev/export_paipu.py <uuid> [输出路径]
    python .dev/export_paipu.py <path/to/snapshots.json> [输出路径]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "game_records"
OUT_DIR = ROOT / "data" / "paipu"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from proto.decoder import GameEvent  # noqa: E402
from replay.adapter import events_to_paipu  # noqa: E402


def load_snapshots(arg: str):
    path = Path(arg)
    if not path.exists():
        path = CACHE_DIR / f"{arg}.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到快照文件: {path}")
    return json.loads(path.read_text(encoding="utf-8")), path


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python .dev/export_paipu.py <uuid 或 JSON 路径> [输出路径]")
        return

    data, path = load_snapshots(sys.argv[1])
    uuid = data.get("uuid") or path.stem
    events = [
        GameEvent(
            step=s["step"],
            type=s["event_type"],
            full_name="",
            seat=s["event_summary"].get("seat"),
            data=dict(s["event_summary"]),
        )
        for s in data.get("snapshots", [])
    ]

    paipu = events_to_paipu(events, head={"uuid": uuid, "title": uuid})

    if len(sys.argv) >= 3:
        out = Path(sys.argv[2])
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{uuid}.json"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(paipu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出: {out}")
    print(f"局数: {len(paipu['log'])}")


if __name__ == "__main__":
    main()
