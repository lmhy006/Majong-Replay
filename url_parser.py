"""雀魂牌谱 URL 解析模块。

职责：
    校验用户输入牌谱链接，提取并校验雀魂对局唯一 ID。

支持两种雀魂牌谱链接（详见开发文档 5.1.1 与社区协议分析）：

    普通牌谱:
        https://game.maj-soul.com/1/?paipu=200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_a89702544
    匿名牌谱:
        https://game.maj-soul.com/1/?paipu=jijpmr-0415suwv-971c-67ei-ilom-qottvksmnvnn_a89702544_2

链接结构说明：
    * UUID 部分: 6位(对局结束日期 YYMMDD，匿名时被编码) + 8-4-4-4-12 位小写字母数字
    * 可选后缀:  `_a<match_id>` 指定主视角账号；`_2` 表示匿名牌谱
    * 仅由 数字/小写字母/短横线/下划线 组成

非法链接（无 paipu 参数、ID 格式错误、含非法字符等）直接抛出异常。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 雀魂官方域名（后缀匹配，兼容 www./game. 等子域名）
MAJSOUL_DOMAINS = ("majsoul.com", "maj-soul.com")

# UUID 部分：6 + 8-4-4-4-12 段，仅小写字母与数字
PAIPU_UUID_PATTERN = (
    r"[a-z0-9]{6}-[a-z0-9]{8}-[a-z0-9]{4}-"
    r"[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}"
)
_PAIPU_UUID_RE = re.compile(rf"^{PAIPU_UUID_PATTERN}$")
# 完整 paipu 值：UUID [+ _a<match_id>] [+ _2]
_PAIPU_FULL_RE = re.compile(
    rf"^({PAIPU_UUID_PATTERN})(?:_a(\d+))?(?:_2)?$"
)

# 匿名牌谱 UUID 编码参数（36 字符模 + 固定偏移 17，见社区逆向分析）
_ENCODE_LEN = 36
_ENCODE_OFFSET = 17


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class PaipuUrlError(ValueError):
    """雀魂牌谱链接非法。"""


class PaipuIdError(ValueError):
    """雀魂牌谱对局 ID 非法。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaipuInfo:
    """牌谱链接解析结果。"""

    paipu: str                  # paipu 参数完整值（含后缀）
    uuid: str                   # 对局唯一 ID（不含 _a / _2 后缀）
    match_id: Optional[str]     # _a 后的主视角账号 ID（无则 None）
    anonymous: bool             # 是否匿名牌谱（带 _2 后缀）
    date: Optional[date]        # 普通牌谱的首段日期（匿名编码后无法识别则为 None）
    url: str                    # 原始输入链接

    def __str__(self) -> str:  # pragma: no cover - 仅调试展示
        suffix = "_2" if self.anonymous else ""
        mid = f"_a{self.match_id}" if self.match_id else ""
        return f"{self.uuid}{mid}{suffix}"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _char_to_index(ch: str) -> int:
    """将 0-9/a-z 映射为 0-35 的下标。"""
    if "0" <= ch <= "9":
        return ord(ch) - ord("0")
    if "a" <= ch <= "z":
        return ord(ch) - ord("a") + 10
    raise PaipuIdError(f"非法字符 {ch!r}：牌谱 ID 仅允许小写字母与数字")


def _index_to_char(idx: int) -> str:
    """将 0-35 的下标映射回 0-9/a-z 字符。"""
    if 0 <= idx <= 9:
        return chr(idx + ord("0"))
    if 10 <= idx < _ENCODE_LEN:
        return chr(idx - 10 + ord("a"))
    raise PaipuIdError(f"非法下标 {idx}")  # pragma: no cover


def _shift_encode(uuid: str) -> str:
    """逐字符循环右移编码：普通牌谱 UUID -> 匿名牌谱 UUID。"""
    chars = []
    for i, ch in enumerate(uuid):
        if ch == "-":
            chars.append(ch)
        else:
            idx = _char_to_index(ch)
            chars.append(_index_to_char((idx + _ENCODE_OFFSET + i) % _ENCODE_LEN))
    return "".join(chars)


def _shift_decode(uuid: str) -> str:
    """逐字符循环左移解码：匿名牌谱 UUID -> 普通牌谱 UUID。"""
    chars = []
    for i, ch in enumerate(uuid):
        if ch == "-":
            chars.append(ch)
        else:
            idx = _char_to_index(ch)
            chars.append(_index_to_char((idx - _ENCODE_OFFSET - i) % _ENCODE_LEN))
    return "".join(chars)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def encode_anonymous_uuid(uuid: str) -> str:
    """普通牌谱 UUID -> 匿名牌谱 UUID（EncodePaipuUUID 的 Python 实现）。"""
    if not _PAIPU_UUID_RE.match(uuid):
        raise PaipuIdError(f"非法普通牌谱 UUID：{uuid!r}")
    return _shift_encode(uuid)


def decode_anonymous_uuid(uuid: str) -> str:
    """匿名牌谱 UUID -> 普通牌谱 UUID（DecodePaipuUUID 的 Python 实现）。"""
    if not _PAIPU_UUID_RE.match(uuid):
        raise PaipuIdError(f"非法牌谱 UUID：{uuid!r}")
    return _shift_decode(uuid)


def validate_paipu(paipu: str) -> str:
    """校验完整 paipu 值并返回对局唯一 ID（UUID 部分）。

    接受的形态：
        UUID
        UUID_a<match_id>
        UUID_2 / UUID_a<match_id>_2   （匿名牌谱）
    """
    paipu = paipu.strip()
    if not paipu:
        raise PaipuIdError("paipu 参数为空")
    m = _PAIPU_FULL_RE.match(paipu)
    if not m:
        raise PaipuIdError(
            "非法牌谱 ID：应为 6-8-4-4-4-12 段的小写字母/数字，"
            "可带 _a<账号ID> 与 _2 后缀（如 "
            "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_a89702544）"
        )
    return m.group(1)


def extract_paipu_value(url: str) -> str:
    """从链接中提取 paipu 参数值（宽松取第一个）。"""
    if not url or not url.strip():
        raise PaipuUrlError("牌谱链接为空")
    url = url.strip()
    # 残缺链接：直接以 paipu= 开头
    if url.startswith("paipu="):
        return url[len("paipu="):].strip()
    if "://" not in url:
        # 允许直接粘贴 paipu=xxx 形式的残缺链接
        url = "https://" + url
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("paipu", [])
    if not values:
        raise PaipuUrlError(f"链接中未找到 paipu 参数：{url!r}")
    return values[0].strip()


def parse_paipu_url(url: str, check_host: bool = True) -> PaipuInfo:
    """解析雀魂牌谱链接，返回结构化结果；非法链接抛出 PaipuUrlError。

    Args:
        url: 雀魂牌谱链接（如 https://game.maj-soul.com/1/?paipu=xxx）
        check_host: 是否校验链接域名属于雀魂官方域名。
    """
    if not url or not url.strip():
        raise PaipuUrlError("牌谱链接为空")
    raw = url.strip()

    # 残缺链接（仅含 paipu=xxx）：不校验域名，直接取值
    if raw.startswith("paipu="):
        paipu = raw[len("paipu="):].strip()
    else:
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urlparse(raw)
        if check_host and parsed.hostname:
            host = parsed.hostname.lower()
            if not any(host == d or host.endswith("." + d) for d in MAJSOUL_DOMAINS):
                raise PaipuUrlError(
                    f"非雀魂官方域名：{host!r}（支持 {', '.join(MAJSOUL_DOMAINS)}）"
                )
        paipu = extract_paipu_value(raw)
    uuid = validate_paipu(paipu)
    m = _PAIPU_FULL_RE.match(paipu)
    assert m is not None  # validate_paipu 已保证匹配
    match_id = m.group(2)
    anonymous = bool(paipu.endswith("_2"))

    # 普通牌谱首段为对局结束日期 YYMMDD（匿名牌谱首段已被编码，跳过解析）
    head = uuid.split("-", 1)[0]
    game_date: Optional[date] = None
    if not anonymous:
        if not head.isdigit():
            raise PaipuUrlError(f"普通牌谱首段应为日期 YYMMDD：{head!r}")
        try:
            yy, mm, dd = int(head[0:2]), int(head[2:4]), int(head[4:6])
            year = 2000 + yy if yy < 70 else 1900 + yy
            game_date = date(year, mm, dd)
        except ValueError:
            raise PaipuUrlError(f"普通牌谱首段不是合法日期：{head!r}") from None

    return PaipuInfo(
        paipu=paipu,
        uuid=uuid,
        match_id=match_id,
        anonymous=anonymous,
        date=game_date,
        url=raw,
    )
