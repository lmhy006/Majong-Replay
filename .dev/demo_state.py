#!/usr/bin/env python3
"""演示：对局状态机（阶段三验证用）。

用法：
    python .dev/demo_state.py                # 使用内置自洽小牌谱
    python .dev/demo_state.py <events.json>  # 使用自己导出的 events JSON
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from game_state.game_simulator import simulate_from_dicts  # noqa: E402


def _builtin_events():
    """与单元测试一致的自洽小牌谱：吃碰 -> 暗杠 -> 立直 -> 和牌 -> 第二局 -> 流局。"""
    return [
        {
            "step": 1,
            "type": "new_round",
            "seat": None,
            "data": {
                "chang": 0, "ju": 0, "ben": 0,
                "scores": [25000, 25000, 25000, 25000],
                "liqibang": 0,
                "tiles0": ["A"] * 14,
                "tiles1": ["B"] * 11 + ["A", "A"],
                "tiles2": ["C"] * 13,
                "tiles3": ["D"] * 13,
                "dora": "1z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 2,
            "type": "discard_tile", "seat": 0,
            "data": {"seat": 0, "tile": "A", "is_liqi": False},
        },
        {
            "step": 3,
            "type": "chi_peng_gang", "seat": 1,
            "data": {"seat": 1, "type": 1, "tiles": ["A", "A", "A"], "froms": [1, 1, 0]},
        },
        {
            "step": 4,
            "type": "an_gang_add_gang", "seat": 1,
            "data": {"seat": 1, "type": 3, "tiles": "B"},
        },
        {
            "step": 5,
            "type": "deal_tile", "seat": 1,
            "data": {"seat": 1, "tile": "E", "left_tile_count": 69},
        },
        {
            "step": 6,
            "type": "discard_tile", "seat": 1,
            "data": {"seat": 1, "tile": "E", "is_liqi": True, "is_wliqi": False},
        },
        {
            "step": 7,
            "type": "hu", "seat": 1,
            "data": {"seat": 1, "hules": [{"seat": 1, "zimo": True}],
                     "scores": [25000, 24000, 25000, 25000]},
        },
        {
            "step": 8,
            "type": "new_round", "seat": None,
            "data": {
                "chang": 0, "ju": 1, "ben": 0,
                "scores": [25000, 24000, 25000, 25000],
                "liqibang": 0,
                "tiles0": ["C"] * 13,
                "tiles1": ["D"] * 14,
                "tiles2": ["A"] * 13,
                "tiles3": ["B"] * 13,
                "dora": "2z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 9,
            "type": "discard_tile", "seat": 1,
            "data": {"seat": 1, "tile": "D", "is_liqi": False},
        },
        {
            "step": 10,
            "type": "no_tile", "seat": None,
            "data": {"gameend": True,
                     "scores": [{"seat": 0, "delta_scores": [1000, 1000, -1000, -1000]}]},
        },
    ]


def _fmt_player(p: dict) -> str:
    liqi = "立直" if (p.get("liqi") and p["liqi"].get("declared")) else "-"
    return (
        f"P{p['seat']}:手{len(p['hand'])} 河{len(p['discards'])} "
        f"副{len(p['melds'])} {p['score']} {liqi}"
    )


def main() -> None:
    if len(sys.argv) > 1:
        raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            events = raw.get("events", raw)
        else:
            events = raw
        src = sys.argv[1]
    else:
        events = _builtin_events()
        src = "builtin"

    snapshots = simulate_from_dicts(events)
    print(f"来源: {src}  事件数: {len(events)}  快照数: {len(snapshots)}\n")
    for s in snapshots:
        d = s.model_dump()
        print(
            f"[{d['step']:3d}] {d['event_type']:20s} "
            f"庄={d['dealer_seat']} 棒={d['liqibang']} 余={d['left_tile_count']} | "
            + " | ".join(_fmt_player(p) for p in d["players"])
        )


if __name__ == "__main__":
    main()
