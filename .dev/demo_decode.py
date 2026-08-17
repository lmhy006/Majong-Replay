#!/usr/bin/env python3
"""演示：解码真实牌谱样例并打印事件流（阶段二验证用）。

用法：
    python .dev/demo_decode.py            # 解码内置 fixture（无需网络/token）
    python .dev/demo_decode.py <文件路径>  # 解码自己拉取的牌谱 .bin 文件
"""
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

import protocol_pb2 as pb  # noqa: E402
from proto.decoder import decode_paipu  # noqa: E402


def _load_data(path: Path) -> bytes:
    """兼容两种输入：ResGameRecord 序列化 / 其 data 字段字节 / base64 文本。"""
    raw = path.read_bytes()
    # 尝试按 ResGameRecord 解析
    try:
        res = pb.ResGameRecord()
        res.ParseFromString(raw)
        if res.data:
            return bytes(res.data)
    except Exception:
        pass
    # 尝试 base64 文本（fixture 格式）
    try:
        decoded = base64.b64decode(raw.strip(), validate=True)
        res = pb.ResGameRecord()
        res.ParseFromString(decoded)
        if res.data:
            return bytes(res.data)
    except Exception:
        pass
    return raw


def main() -> None:
    if len(sys.argv) > 1:
        data = _load_data(Path(sys.argv[1]))
        src = sys.argv[1]
    else:
        fx = ROOT / "tests" / "fixtures" / "sample.res.b64"
        data = _load_data(fx)
        src = "tests/fixtures/sample.res.b64"

    result = decode_paipu(data)
    print(f"来源: {src}")
    print(f"牌谱版本: {result.version}  事件数: {len(result.events)}\n")

    for e in result.events:
        seat = e.seat if e.seat is not None else "-"
        extra = ""
        if e.type == "new_round":
            extra = f" 场{e.data.get('chang',0)} 局{e.data.get('ju',0)} 本场{e.data.get('ben',0)}"
        elif e.type == "deal_tile":
            extra = f" 摸牌={e.data.get('tile')} 余牌={e.data.get('left_tile_count')}"
        elif e.type == "discard_tile":
            extra = f" 打牌={e.data.get('tile')} 立直={bool(e.data.get('is_liqi'))}"
        elif e.type == "chi_peng_gang":
            extra = f" type={e.data.get('type')} 牌={e.data.get('tiles')}"
        elif e.type == "an_gang_add_gang":
            extra = f" type={e.data.get('type')} 牌={e.data.get('tiles')}"
        elif e.type == "hu":
            extra = f" 和牌信息={len(e.data.get('hules', []))} 条"
        elif e.type == "no_tile":
            extra = " 无牌可摸"
        print(f"[{e.step:3d}] {e.type:20s} 座位={seat}{extra}")


if __name__ == "__main__":
    main()
