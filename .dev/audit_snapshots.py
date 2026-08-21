#!/usr/bin/env python3
"""审计对局快照缓存，检查状态机不变量（阶段三真实牌谱回归用）。

用法：
    python .dev/audit_snapshots.py <uuid>
    python .dev/audit_snapshots.py <path/to/snapshots.json>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "game_records"


def load_snapshots(arg: str):
    path = Path(arg)
    if not path.exists():
        path = CACHE_DIR / f"{arg}.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到快照文件: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, path


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python .dev/audit_snapshots.py <uuid 或 JSON 文件路径>")
        return

    try:
        data, path = load_snapshots(sys.argv[1])
    except FileNotFoundError as exc:
        print(exc)
        return

    snaps = data.get("snapshots", [])
    issues = []

    def add(step, ev, msg):
        issues.append((step, ev, msg))

    # ---------- 基础结构检查 ----------
    for i, s in enumerate(snaps):
        step = s.get("step", i + 1)
        ev = s.get("event_type", "?")
        players = s.get("players", [])
        if len(players) != 4:
            add(step, ev, f"players 数量 {len(players)} != 4")
        for p in players:
            hand_len = len(p.get("hand", []))
            if hand_len > 14:
                add(step, ev, f"P{p.get('seat')} 手牌数 {hand_len} > 14")

    # ---------- 相邻事件状态变化检查 ----------
    for i in range(1, len(snaps)):
        prev = snaps[i - 1]
        cur = snaps[i]
        step = cur.get("step", i + 1)
        ev = cur.get("event_type", "?")
        data = cur.get("event_summary", {})
        seat = data.get("seat")
        if seat is None or not isinstance(seat, int):
            continue
        if not (0 <= seat < 4):
            continue

        pp = cur["players"][seat]
        prev_p = prev["players"][seat]
        hand_delta = len(pp["hand"]) - len(prev_p["hand"])
        discards_delta = len(pp["discards"]) - len(prev_p["discards"])
        melds_delta = len(pp["melds"]) - len(prev_p["melds"])

        if ev == "deal_tile":
            if hand_delta != 1:
                add(step, ev, f"P{seat} deal_tile 手牌变化 {hand_delta} != +1")
        elif ev == "discard_tile":
            if hand_delta != -1:
                add(step, ev, f"P{seat} discard_tile 手牌变化 {hand_delta} != -1")
            if discards_delta != 1:
                add(step, ev, f"P{seat} discard_tile 牌河变化 {discards_delta} != +1")
        elif ev == "chi_peng_gang":
            froms = data.get("froms") or []
            own = sum(1 for f in froms if f == seat)
            expected = -own
            if hand_delta != expected:
                add(step, ev, f"P{seat} chi_peng_gang 手牌变化 {hand_delta} != {expected}")
            if melds_delta != 1:
                add(step, ev, f"P{seat} chi_peng_gang 副露变化 {melds_delta} != +1")
            for f in set(froms):
                if f != seat:
                    prev_f = prev["players"][f]
                    cur_f = cur["players"][f]
                    delta = len(cur_f["discards"]) - len(prev_f["discards"])
                    if delta != -froms.count(f):
                        add(step, ev, f"P{f} 被鸣走牌河变化 {delta} != {-froms.count(f)}")
        elif ev == "an_gang_add_gang":
            typ = data.get("type")
            if typ == 3:  # 暗杠
                if hand_delta != -4:
                    add(step, ev, f"P{seat} 暗杠手牌变化 {hand_delta} != -4")
            elif typ == 2:  # 加杠
                if hand_delta != -1:
                    add(step, ev, f"P{seat} 加杠手牌变化 {hand_delta} != -1")
        elif ev == "ba_bei":
            if hand_delta != -1:
                add(step, ev, f"P{seat} ba_bei 手牌变化 {hand_delta} != -1")

    # ---------- 立直检查 ----------
    for i, s in enumerate(snaps):
        step = s.get("step", i + 1)
        ev = s.get("event_type", "?")
        data = s.get("event_summary", {})
        if ev == "discard_tile" and data.get("is_liqi"):
            seat = data.get("seat")
            if seat is not None:
                p = s["players"][seat]
                liqi = p.get("liqi")
                if not liqi or not liqi.get("declared"):
                    add(step, ev, f"P{seat} is_liqi=True 但快照 liqi.declared 不为 True")
                elif liqi.get("score_cost", 0) != 1000:
                    add(step, ev, f"P{seat} 立直 score_cost={liqi.get('score_cost')} != 1000")
        for p in s["players"]:
            liqi = p.get("liqi")
            if liqi and liqi.get("declared") and liqi.get("score_cost", 0) != 1000:
                add(step, ev, f"P{p['seat']} 立直状态 score_cost={liqi.get('score_cost')} != 1000")

    # ---------- new_round 检查 ----------
    for i, s in enumerate(snaps):
        step = s.get("step", i + 1)
        if s.get("event_type") != "new_round":
            continue
        dealer = s.get("dealer_seat")
        players = s["players"]
        for p in players:
            if p["seat"] == dealer:
                if len(p["hand"]) != 14:
                    add(step, "new_round", f"庄家 P{dealer} 手牌 {len(p['hand'])} != 14")
            else:
                if len(p["hand"]) != 13:
                    add(step, "new_round", f"闲家 P{p['seat']} 手牌 {len(p['hand'])} != 13")
            if p["discards"] or p["melds"] or p.get("liqi"):
                add(step, "new_round", f"P{p['seat']} 新局未重置 discards/melds/liqi")

    print(f"文件: {path}")
    print(f"快照数: {len(snaps)}")
    print(f"发现问题: {len(issues)}")
    if issues:
        print("\n前 50 个问题:")
        for step, ev, msg in issues[:50]:
            print(f"  step {step} [{ev}] {msg}")
    else:
        print("未发现明显状态机偏差。")


if __name__ == "__main__":
    main()
