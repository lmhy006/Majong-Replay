"""majiang-ui 回放数据适配器（阶段四）。

将阶段三的事件流/快照转换为 @kobalab/majiang-ui 可识别的 paipu 对象：

    paipu = {
        title:  str,
        player: [str, str, str, str],
        qijia:  int,          # 起家（第一局庄家）绝对座位
        defen:  [int]*4,      # 最终点数（绝对座位顺序）
        log:    [ [ {qipai|zimo|dapai|fulou|gang|gangzimo|kaigang|hule|pingju}, ... ], ... ]
    }

转换基于事件流 + 状态机快照：事件决定动作，快照提供手牌/副露/点数等完整状态。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from proto.decoder import GameEvent

from game_state.game_simulator import simulate
from game_state.state_model import GameSnapshot, Meld


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _dealer_seat(data: Dict) -> int:
    """从 new_round 数据判定庄家：起手 14 张的座位优先，否则用场/局推导。"""
    for i in range(4):
        if len(data.get(f"tiles{i}", []) or []) == 14:
            return i
    return (int(data.get("chang", 0) or 0) * 4 + int(data.get("ju", 0) or 0)) % 4


def _to_mj_tile(tile: str) -> str:
    """雀魂 tile '1p' -> majiang-ui tile 'p1'；'0m' -> 'm0'。"""
    if not tile:
        return tile
    return tile[1] + tile[0]


def _hand_to_paistr(hand: Sequence[str]) -> str:
    """手牌列表 -> majiang-ui paistr（如 '123m456p789s123z'）。"""
    groups: Dict[str, List[str]] = {"m": [], "p": [], "s": [], "z": []}
    for tile in hand:
        if not tile:
            continue
        n, s = tile[0], tile[1]
        groups.setdefault(s, []).append(n)
    parts = []
    for s in "mpsz":
        if groups.get(s):
            parts.append(s + "".join(sorted(groups[s])))
    return "".join(parts)


def _direction(seat: int, from_seat: int) -> str:
    """相对方向符号：+ 下家、= 对家、- 上家。"""
    diff = (from_seat - seat) % 4
    if diff == 1:
        return "+"
    if diff == 2:
        return "="
    if diff == 3:
        return "-"
    return ""


def _normalize_nums(raw_nums: Sequence[int]) -> List[int]:
    """将牌数字归一化：0（赤5）最多保留一个，且保留其原始位置，多余 0 转 5。"""
    seen_zero = False
    nums: List[int] = []
    for n in raw_nums:
        if n == 0:
            if seen_zero:
                nums.append(5)
            else:
                nums.append(0)
                seen_zero = True
        else:
            nums.append(n)
    return nums


def _reorder_claimed(nums: Sequence[int], claimed_idx: Optional[int]) -> List[int]:
    """将被鸣牌移到列表最后（符号前最后一位），其余保持原顺序。"""
    if claimed_idx is None:
        return list(nums)
    claimed = nums[claimed_idx]
    others = [n for i, n in enumerate(nums) if i != claimed_idx]
    return others + [claimed]


def _mianzi_from_meld(meld: Meld, seat: int) -> str:
    """将内部 Meld 转换为 majiang-ui 副露字符串。

    输出必须符合 Majiang.Shoupai.valid_mianzi 的规范化格式，例如：
        吃   [mps]3-45       （被鸣牌在符号前，其余在符号后）
        碰   [mps]505=       （其余降序 + 被鸣牌 + 方向）
        大明杠 [mps]5505+     （其余降序 + 被鸣牌 + 方向）
        暗杠 [mps]5550
        加杠 [mps]505=5      （碰规范 + 加杠牌）
    """
    if not meld.tiles:
        return ""
    s = meld.tiles[0][1]
    raw_nums = [int(t[0]) for t in meld.tiles]
    nums = _normalize_nums(raw_nums)

    def claimed_index() -> Optional[int]:
        for i, f in enumerate(meld.froms):
            if f != seat:
                return i
        return None

    if meld.type == 0:  # 吃
        claimed_idx = claimed_index() or 0
        direction = _direction(seat, meld.froms[claimed_idx])
        claimed_num = nums[claimed_idx]
        other_nums = [nums[i] for i in range(len(nums)) if i != claimed_idx]

        def _key(n: int) -> int:
            return 5 if n == 0 else n

        claimed_val = _key(claimed_num)
        other_sorted = sorted(other_nums, key=_key)
        if claimed_val < _key(other_sorted[0]):
            # 被鸣牌最小：符号在开头
            return f"{s}{claimed_num}{direction}{''.join(str(n) for n in other_sorted)}"
        if claimed_val > _key(other_sorted[-1]):
            # 被鸣牌最大：符号在末尾
            return f"{s}{''.join(str(n) for n in other_sorted)}{claimed_num}{direction}"
        # 被鸣牌中间：符号在中间
        smaller = [n for n in other_nums if _key(n) < claimed_val]
        larger = [n for n in other_nums if _key(n) > claimed_val]
        return (
            f"{s}{''.join(str(n) for n in sorted(smaller, key=_key))}"
            f"{claimed_num}{direction}"
            f"{''.join(str(n) for n in sorted(larger, key=_key))}"
        )

    if meld.type in (1, 2):  # 碰 / 大明杠
        claimed_idx = claimed_index() or 0
        direction = _direction(seat, meld.froms[claimed_idx])
        claimed_num = nums[claimed_idx]
        other_nums = sorted(
            (nums[i] for i in range(len(nums)) if i != claimed_idx),
            reverse=True,
        )
        return f"{s}{''.join(str(n) for n in other_nums)}{claimed_num}{direction}"

    if meld.type == 3:  # 暗杠
        return f"{s}{''.join(str(n) for n in sorted(nums, reverse=True))}"

    if meld.type == 4:  # 加杠：前 3 张是碰，第 4 张是加杠牌
        base_froms = meld.froms[:3] or [seat]
        claimed_idx = next(
            (i for i, f in enumerate(base_froms) if f != seat),
            None,
        )
        direction = _direction(seat, base_froms[claimed_idx] if claimed_idx is not None else seat)
        base_nums = nums[:3]
        if claimed_idx is None:
            base_str = f"{s}{''.join(str(n) for n in sorted(base_nums, reverse=True))}"
        else:
            claimed_num = base_nums[claimed_idx]
            other_nums = sorted(
                (base_nums[i] for i in range(3) if i != claimed_idx),
                reverse=True,
            )
            base_str = f"{s}{''.join(str(n) for n in other_nums)}{claimed_num}{direction}"
        add_num = nums[-1] if len(nums) >= 4 else 5
        return f"{base_str}{add_num}"

    # 其他类型（如拔北）暂不支持，返回空
    return ""


def _player_paistr(
    snapshot: GameSnapshot,
    abs_seat: int,
    hand_override: Optional[Sequence[str]] = None,
    append_tile: Optional[str] = None,
) -> str:
    """从快照生成某玩家完整手牌 paistr（手牌 + 副露）。

    append_tile 会追加到“手牌部分”末尾，用于荣和牌等需要作为摸牌识别的牌。
    """
    player = snapshot.players[abs_seat]
    hand = hand_override if hand_override is not None else player.hand
    hand_str = _hand_to_paistr(hand)
    if append_tile:
        hand_str += _to_mj_tile(append_tile)
    meld_strs = [_mianzi_from_meld(m, abs_seat) for m in player.melds]
    meld_strs = [m for m in meld_strs if m]
    if meld_strs:
        return hand_str + "," + ",".join(meld_strs)
    return hand_str


def _abs_to_rel(seat: int, qijia: int, ju: int) -> int:
    """绝对座位 -> majiang-ui 相对座位。"""
    return (seat - qijia - ju) % 4


def _rel_scores(scores: Sequence[int], qijia: int, ju: int) -> List[int]:
    """绝对顺序点数/变化 -> 相对顺序。"""
    return [int(scores[(qijia + ju + l) % 4]) for l in range(4)]


# ---------------------------------------------------------------------------
# 主转换
# ---------------------------------------------------------------------------


def events_to_paipu(
    events: Sequence[GameEvent],
    head: Optional[Dict] = None,
    strict: bool = True,
) -> Dict:
    """将事件流转换为 majiang-ui paipu 对象。"""
    snapshots = simulate(events, head=head, strict=strict)
    if not events:
        raise ValueError("事件流为空")

    logs: List[List[Dict]] = []
    current_log: List[Dict] = []

    qijia: Optional[int] = None
    current_ju = 0
    prev_event_type: Optional[str] = None
    last_discard_seat: Optional[int] = None
    last_discard_tile: str = ""

    for event, snap in zip(events, snapshots):
        data = event.data

        if event.type == "new_round":
            if current_log:
                logs.append(current_log)
                current_log = []
            if qijia is None:
                qijia = _dealer_seat(data)
            current_ju = int(data.get("ju", 0) or 0)

            baopai = list(data.get("doras") or [])
            if not baopai and data.get("dora"):
                baopai = [data["dora"]]

            qipai = {
                "zhuangfeng": int(data.get("chang", 0) or 0),
                "jushu": current_ju,
                "changbang": int(data.get("ben", 0) or 0),
                "lizhibang": int(data.get("liqibang", 0) or 0),
                "baopai": [_to_mj_tile(t) for t in baopai],
                "shoupai": [],
                "defen": [],
            }
            for l in range(4):
                abs_seat = (qijia + current_ju + l) % 4
                qipai["shoupai"].append(
                    _hand_to_paistr(data.get(f"tiles{abs_seat}", []) or [])
                )
                scores = data.get("scores") or [25000] * 4
                qipai["defen"].append(int(scores[abs_seat]))
            current_log.append({"qipai": qipai})

        elif event.type == "deal_tile":
            if event.seat is None:
                continue
            rel = _abs_to_rel(event.seat, qijia or 0, current_ju)
            if prev_event_type in ("an_gang_add_gang", "ba_bei"):
                current_log.append({"gangzimo": {"l": rel, "p": _to_mj_tile(data.get("tile", ""))}})
            else:
                current_log.append({"zimo": {"l": rel, "p": _to_mj_tile(data.get("tile", ""))}})

        elif event.type == "discard_tile":
            if event.seat is None:
                continue
            rel = _abs_to_rel(event.seat, qijia or 0, current_ju)
            tile = _to_mj_tile(data.get("tile", ""))
            if data.get("is_liqi"):
                tile += "*"
            current_log.append({"dapai": {"l": rel, "p": tile}})
            last_discard_seat = event.seat
            last_discard_tile = data.get("tile", "")

        elif event.type == "chi_peng_gang":
            if event.seat is None:
                continue
            rel = _abs_to_rel(event.seat, qijia or 0, current_ju)
            tiles = list(data.get("tiles", []) or [])
            froms = list(data.get("froms", []) or [])
            # 被鸣走的牌以实际打出的牌为准（可能包含赤0，meld.tiles 中可能被归一化为5）
            if last_discard_seat is not None and last_discard_tile:
                for i, f in enumerate(froms):
                    if f == last_discard_seat:
                        tiles[i] = last_discard_tile
                        break
            meld = Meld(
                type=int(data.get("type", 0) or 0),
                tiles=tiles,
                froms=froms,
            )
            m = _mianzi_from_meld(meld, event.seat)
            if m:
                current_log.append({"fulou": {"l": rel, "m": m}})

        elif event.type == "an_gang_add_gang":
            if event.seat is None:
                continue
            rel = _abs_to_rel(event.seat, qijia or 0, current_ju)
            typ = int(data.get("type", 0) or 0)
            tile = data.get("tiles", "")
            if not tile:
                continue
            s = tile[1]
            n = tile[0]
            if typ == 3:  # 暗杠
                m = f"{s}{n}{n}{n}{n}"
            elif typ == 2:  # 加杠：优先从快照中找到升级后的副露字符串
                target = None
                for meld in snap.players[event.seat].melds:
                    if meld.type == 4 and meld.tiles and meld.tiles[0] == tile:
                        target = meld
                        break
                m = _mianzi_from_meld(target, event.seat) if target else f"{s}{n}{n}{n}+{n}"
            else:
                continue
            current_log.append({"gang": {"l": rel, "m": m}})

        elif event.type == "ba_bei":
            # 三麻拔北：majiang-ui 基础版不支持，先跳过
            pass

        elif event.type == "hu":
            hules = data.get("hules", []) or []
            if not hules:
                continue
            for h in hules:
                abs_seat = int(h.get("seat", event.seat if event.seat is not None else 0))
                rel = _abs_to_rel(abs_seat, qijia or 0, current_ju)
                # 和牌手牌：优先用牌谱给的 hand；荣和时把荣和牌追加到手牌末尾
                hand_override = list(h.get("hand") or [])
                append_tile = None
                if not h.get("zimo", False) and h.get("hu_tile"):
                    append_tile = h["hu_tile"]
                if not hand_override:
                    hand_override = list(snap.players[abs_seat].hand)
                shoupai = _player_paistr(
                    snap, abs_seat,
                    hand_override=hand_override,
                    append_tile=append_tile,
                )
                baojia = None
                if not h.get("zimo", False):
                    if last_discard_seat is not None:
                        baojia = _abs_to_rel(last_discard_seat, qijia or 0, current_ju)
                delta = data.get("delta_scores") or [0] * 4
                fenpei = _rel_scores(delta, qijia or 0, current_ju) if len(delta) == 4 else [0] * 4
                hule_event = {
                    "l": rel,
                    "shoupai": shoupai,
                    "baojia": baojia,
                    "fenpei": fenpei,
                    "fubaopai": [_to_mj_tile(t) for t in (data.get("doras", []) or [])],
                }
                current_log.append({"hule": hule_event})

        elif event.type in ("no_tile", "liu_ju"):
            # 流局名称
            if event.type == "no_tile":
                name = "流し満貫" if data.get("liujumanguan") else "流局"
            else:
                typ = int(data.get("type", 0) or 0)
                name = f"流局(type={typ})"
            shoupai = [_player_paistr(snap, i) for i in range(4)]
            delta = [0] * 4
            scores_info = data.get("scores") or []
            if scores_info:
                first = scores_info[0]
                if first.get("delta_scores") and len(first["delta_scores"]) == 4:
                    delta = first["delta_scores"]
            fenpei = _rel_scores(delta, qijia or 0, current_ju) if len(delta) == 4 else [0] * 4
            current_log.append({
                "pingju": {
                    "name": name,
                    "shoupai": shoupai,
                    "fenpei": fenpei,
                }
            })

        prev_event_type = event.type

    if current_log:
        logs.append(current_log)

    if qijia is None:
        qijia = 0

    final_scores = list(snapshots[-1].scores) if snapshots else [25000] * 4
    return {
        "title": (head or {}).get("title") or (head or {}).get("uuid") or "雀魂牌谱",
        "player": (head or {}).get("player") or [f"P{i}" for i in range(4)],
        "qijia": qijia,
        "defen": final_scores,
        "log": logs,
    }
