"""proto.decoder 单元测试（阶段二）。

使用两类数据：
    1. 真实牌谱 fixture（tests/fixtures/sample.res.b64，
       来源 Majsoul-to-NAGA MIT 许可的测试夹具）
    2. 手工构造的完整小牌谱（覆盖新旧两种协议版本）
"""

import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

import protocol_pb2 as pb  # noqa: E402
from proto.decoder import (  # noqa: E402
    GameEvent,
    decode_event,
    decode_game_detail_records,
    decode_game_record_data,
    decode_paipu,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.res.b64"


def _load_fixture() -> bytes:
    """返回 fixture 的 ResGameRecord.data（Wrapper 外壳）。"""
    raw = base64.b64decode(FIXTURE.read_bytes())
    res = pb.ResGameRecord()
    res.ParseFromString(raw)
    return bytes(res.data)


def _build_wrapper(name: str, data: bytes) -> bytes:
    w = pb.Wrapper()
    w.name = name
    w.data = data
    return w.SerializeToString()


def _build_fake_detail(version: int = 220000, old_style: bool = False) -> bytes:
    """构造一个包含 新对局->摸牌->打牌->和牌 的 GameDetailRecords。"""
    gd = pb.GameDetailRecords()
    gd.version = version

    # RecordNewRound
    nr = pb.RecordNewRound()
    nr.chang = 0
    nr.ju = 0
    nr.ben = 0
    nr.dora = "1m"
    nr.scores.extend([25000] * 4)
    nr.left_tile_count = 70
    nr.tiles0.extend(["1m", "1m", "1m", "9s"])
    nr.tiles1.extend(["2m", "2m", "9p"])
    nr.tiles2.extend(["3m", "9s", "9s"])
    nr.tiles3.extend(["4m", "5m", "6m"])
    nr.paishan = "5z"

    # RecordDealTile seat=0 tile=7z
    dt = pb.RecordDealTile()
    dt.seat = 0
    dt.tile = "7z"
    dt.left_tile_count = 69

    # RecordDiscardTile seat=0 tile=7z is_liqi=False
    disc = pb.RecordDiscardTile()
    disc.seat = 0
    disc.tile = "7z"

    # RecordHule seat=1（自摸）
    hu = pb.RecordHule()
    info = hu.hules.add()
    info.seat = 1
    info.hu_tile = "9p"
    info.zimo = True
    info.count = 1
    hu.old_scores.extend([25000, 25000, 25000, 25000])
    hu.delta_scores.extend([0, 3000, -1000, -1000, -1000])
    hu.scores.extend([25000, 28000, 24000, 24000])

    events = [nr, dt, disc, hu]
    if old_style:
        for ev in events:
            gd.records.append(_build_wrapper(f".lq.Record{type(ev).__name__[6:]}", ev.SerializeToString()))
    else:
        for ev in events:
            ga = gd.actions.add()
            ga.type = 1
            ga.result = _build_wrapper(
                f".lq.Record{type(ev).__name__[6:]}", ev.SerializeToString()
            )
    return gd.SerializeToString()


class TestDecodeEvent(unittest.TestCase):
    def test_known_event(self):
        nr = pb.RecordNewRound()
        nr.ju = 1
        blob = _build_wrapper(".lq.RecordNewRound", nr.SerializeToString())
        ev = decode_event(blob, step=3)
        self.assertEqual(ev.step, 3)
        self.assertEqual(ev.type, "new_round")
        self.assertEqual(ev.full_name, ".lq.RecordNewRound")
        self.assertEqual(ev.data["ju"], 1)

    def test_unknown_event_kept(self):
        blob = _build_wrapper(".lq.RecordSomethingNew", b"\x08\x01")
        ev = decode_event(blob)
        self.assertTrue(ev.type.startswith("unknown:"))

    def test_seat_zero_preserved(self):
        dt = pb.RecordDealTile()
        dt.seat = 0  # 东家：默认值必须保留
        dt.tile = "1m"
        blob = _build_wrapper(".lq.RecordDealTile", dt.SerializeToString())
        ev = decode_event(blob)
        self.assertEqual(ev.seat, 0)
        self.assertEqual(ev.data["tile"], "1m")


class TestDecodeGameDetail(unittest.TestCase):
    def test_new_style_fake_paipu(self):
        data = _build_fake_detail()
        result = decode_game_detail_records(data)
        self.assertEqual(result.version, 220000)
        self.assertEqual(len(result.events), 4)
        types = [e.type for e in result.events]
        self.assertEqual(types, ["new_round", "deal_tile", "discard_tile", "hu"])
        self.assertEqual(result.events[1].seat, 0)  # seat=0 保留
        self.assertEqual(result.events[2].data["tile"], "7z")
        self.assertEqual(result.events[3].seat, 1)
        self.assertEqual(len(result.events[3].data["hules"]), 1)

    def test_old_style_fake_paipu(self):
        data = _build_fake_detail(version=200000, old_style=True)
        result = decode_game_detail_records(data)
        self.assertEqual(result.version, 200000)
        self.assertEqual(len(result.events), 4)
        self.assertEqual(result.events[0].type, "new_round")

    def test_wrapper_shell(self):
        inner = _build_fake_detail()
        blob = _build_wrapper(".lq.GameDetailRecords", inner)
        result = decode_game_record_data(blob)
        self.assertEqual(len(result.events), 4)


class TestDecodeRealFixture(unittest.TestCase):
    """用真实牌谱数据（Majsoul-to-NAGA 夹具）验证解码器。"""

    @classmethod
    def setUpClass(cls):
        cls.data = _load_fixture()

    def test_fixture_events(self):
        result = decode_paipu(self.data)
        self.assertEqual(result.version, 220000)
        self.assertGreaterEqual(len(result.events), 20)

    def test_fixture_expected_sequence(self):
        result = decode_paipu(self.data)
        # 已知夹具的事件类型序列（前 22 个）
        expected = [
            "new_round", "discard_tile", "chi_peng_gang", "an_gang_add_gang",
            "deal_tile", "discard_tile", "deal_tile", "an_gang_add_gang",
            "deal_tile", "discard_tile", "deal_tile", "discard_tile",
            "hu", "new_round", "deal_tile", "discard_tile",
            "chi_peng_gang", "discard_tile", "hu", "new_round",
            "discard_tile", "no_tile",
        ]
        self.assertEqual([e.type for e in result.events], expected)

    def test_fixture_key_fields(self):
        result = decode_paipu(self.data)
        discards = [e for e in result.events if e.type == "discard_tile"]
        # 第一巡：东家打 2m
        first = discards[0]
        self.assertEqual(first.seat, 0)
        self.assertEqual(first.data["tile"], "2m")
        # 立直标志
        liqi_discards = [e for e in result.events if e.type == "discard_tile" and e.data.get("is_liqi")]
        self.assertEqual(len(liqi_discards), 1)
        self.assertEqual(liqi_discards[0].data["tile"], "4z")
        # 吃：type=0 默认值保留
        chis = [e for e in result.events if e.type == "chi_peng_gang" and e.data.get("type") == 0]
        self.assertEqual(len(chis), 1)
        self.assertEqual(chis[0].data["tiles"], ["6p", "7p", "8p"])


if __name__ == "__main__":
    unittest.main()
