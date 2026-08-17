"""雀魂牌谱 WebSocket 拉取模块（阶段二）。

模拟雀魂网页客户端 WebSocket 握手协议，拉取官方二进制对局数据。

核心流程：
    服务器发现 -> WebSocket 连接 -> 登录（token/账号） -> fetchGameRecord
    -> 返回 ResGameRecord（head + data + data_url）

约束：
    * 单条单次请求，无批量爬取逻辑（规避风控）
    * 连续请求间隔 >= request_interval_seconds（默认 2s）

认证说明（重要）：
    雀魂自 2023 年起阻止程序化账号密码登录（错误码 151），未认证会话调用
    fetchGameRecord 会返回错误码 1004。因此本模块推荐使用 access_token
    登录（从浏览器控制台获取，见 README「获取 access_token」），通过
    oauth2Check / oauth2Login 建立会话。

帧协议（雀魂 liqi RPC）：
    WebSocket 消息 = [类型字节] + 负载
        1 = NOTIFY   负载 = Wrapper{name, data}
        2 = REQUEST  负载 = [2字节小端请求号] + Wrapper{name, data}
        3 = RESPONSE 负载 = [2字节小端请求号] + Wrapper{name, data}
    方法名：.lq.Lobby.fetchGameRecord
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import random
import sys
import time
import uuid
from typing import Any, Dict, Optional

import websockets

# 保证从任意位置 import 都能找到 proto 包
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto"))

import protocol_pb2 as pb  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 雀魂服务器地址（国际服；国服可用 https://www.majsoul.com，需调整 config 解析）
MAJSOUL_HOST = "https://game.maj-soul.com"
DEFAULT_INTERVAL = 2.0  # 连续请求最小间隔（秒），风控保护

# 错误码（实测确认）
ERR_AUTH = 151          # 认证失败（程序化登录被阻止 / token 无效）
ERR_NOT_LOGGED_IN = 1004  # 未登录会话访问受限接口


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class MajsoulError(Exception):
    """雀魂协议通用错误。"""


class MajsoulAuthError(MajsoulError):
    """认证失败（错误码 151）。"""


class MajsoulNotLoggedInError(MajsoulError):
    """未登录会话访问受限接口（错误码 1004）。"""


class MajsoulRpcError(MajsoulError):
    """RPC 调用返回业务错误。"""

    def __init__(self, code: int, message: str = ""):
        self.code = code
        super().__init__(f"RPC error {code}: {message}".strip())


def _error_detail(error) -> str:
    """格式化 Error 消息的详细信息（code + 参数）。"""
    parts = [f"code={error.code}"]
    if error.u32_params:
        parts.append(f"u32={list(error.u32_params)}")
    if error.str_params:
        parts.append(f"str={list(error.str_params)}")
    if error.json_param:
        parts.append(f"json={error.json_param[:100]}")
    return " ".join(parts)


def _error_from_code(code: int, message: str = "") -> MajsoulError:
    if code == ERR_AUTH:
        return MajsoulAuthError(f"认证失败（错误码 151）：{message}".strip())
    if code == ERR_NOT_LOGGED_IN:
        return MajsoulNotLoggedInError(
            "未登录会话无法拉取牌谱（错误码 1004），请先配置 access_token，"
            "详见 README「获取 access_token」"
        )
    return MajsoulRpcError(code, message)


# ---------------------------------------------------------------------------
# RPC 通道（帧协议）
# ---------------------------------------------------------------------------


class MajsoulRPCChannel:
    """雀魂 WebSocket RPC 通道：帧编解码 + 请求-响应匹配。"""

    # 消息类型
    TYPE_NOTIFY = 1
    TYPE_REQUEST = 2
    TYPE_RESPONSE = 3

    def __init__(self, endpoint: str, origin: str = MAJSOUL_HOST):
        self._endpoint = endpoint
        self._origin = origin
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._dispatcher: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Event] = {}
        self._responses: Dict[int, bytes] = {}
        self._next_idx = 1
        self._hooks: Dict[str, list] = {}

    # ---- 连接管理 ----

    async def connect(self, timeout: float = 15.0) -> None:
        self._ws = await websockets.connect(
            self._endpoint, origin=self._origin, open_timeout=timeout
        )
        self._dispatcher = asyncio.create_task(self._dispatch())

    async def close(self) -> None:
        if self._dispatcher:
            self._dispatcher.cancel()
            try:
                await self._dispatcher
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            await self._ws.close()

    def add_hook(self, msg_name: str, hook) -> None:
        self._hooks.setdefault(msg_name, []).append(hook)

    # ---- 帧编解码 ----

    @staticmethod
    def wrap(name: str, data: bytes) -> bytes:
        w = pb.Wrapper()
        w.name = name
        w.data = data
        return w.SerializeToString()

    @staticmethod
    def unwrap(data: bytes) -> pb.Wrapper:
        w = pb.Wrapper()
        w.ParseFromString(data)
        return w

    # ---- 消息分发 ----

    async def _dispatch(self) -> None:
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if not msg:
                    continue
                t = msg[0]
                if t == self.TYPE_NOTIFY:
                    w = self.unwrap(msg[1:])
                    for hook in self._hooks.get(w.name, []):
                        asyncio.create_task(hook(w.data))
                elif t == self.TYPE_RESPONSE:
                    idx = int.from_bytes(msg[1:3], "little")
                    if idx in self._pending:
                        self._responses[idx] = msg
                        self._pending[idx].set()
                # REQUEST（type 2）为服务器主动请求，本模块不处理
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - 网络异常由调用方感知
            logger.warning("RPC 通道异常关闭: %s", exc)

    # ---- 请求 ----

    async def send_request(
        self, name: str, msg: bytes, timeout: float = 30.0
    ) -> bytes:
        """发送 RPC 请求并等待响应，返回响应 Wrapper.data。

        Raises:
            MajsoulError: 响应包含业务错误（error 字段非空）
            asyncio.TimeoutError: 超时未收到响应
        """
        if self._ws is None:
            raise MajsoulError("通道未连接")

        idx = self._next_idx
        self._next_idx = (self._next_idx + 1) % 60007

        pkt = (
            bytes([self.TYPE_REQUEST])
            + idx.to_bytes(2, "little")
            + self.wrap(name, msg)
        )
        evt = asyncio.Event()
        self._pending[idx] = evt
        try:
            await self._ws.send(pkt)
            await asyncio.wait_for(evt.wait(), timeout=timeout)
        finally:
            self._pending.pop(idx, None)

        resp = self._responses.pop(idx, None)
        if resp is None:
            raise MajsoulError(f"请求 {name} 未收到响应（idx={idx}）")

        body = self.unwrap(resp[3:])
        data = body.data

        # 服务端错误：Wrapper.name 为空且 data 为 ResCommon{error}
        if body.name in ("", ".lq.Error"):
            res = pb.ResCommon()
            res.ParseFromString(data)
            if res.error.code:
                raise _error_from_code(res.error.code, _error_detail(res.error))
        return data

    async def call(self, name: str, req, timeout: float = 30.0) -> bytes:
        """发送 protobuf 请求消息，返回响应 data 字节。"""
        return await self.send_request(name, req.SerializeToString(), timeout)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


def _fill_login_req(req, token: str, credentials: dict):
    """按字段级复刻浏览器登录参数到 ReqOauth2Login。"""
    req.access_token = token
    if credentials.get("type") is not None:
        req.type = credentials["type"]
    if credentials.get("random_key"):
        req.random_key = credentials["random_key"]
    if credentials.get("client_version_string"):
        req.client_version_string = credentials["client_version_string"]
    if credentials.get("tag"):
        req.tag = credentials["tag"]
    if credentials.get("reconnect") is not None:
        req.reconnect = credentials["reconnect"]
    if credentials.get("gen_access_token") is not None:
        req.gen_access_token = credentials["gen_access_token"]
    if credentials.get("version"):
        req.version = credentials["version"]
    for cp in credentials.get("currency_platforms") or []:
        req.currency_platforms.append(cp)
    cv = credentials.get("client_version")
    if cv:
        if cv.get("resource"):
            req.client_version.resource = cv["resource"]
        if cv.get("package"):
            req.client_version.package = cv["package"]
    dev = credentials.get("device")
    if dev:
        for k, v in dev.items():
            if hasattr(req.device, k):
                setattr(req.device, k, v)
    return req


class MajsoulClient:
    """雀魂牌谱拉取客户端。"""

    def __init__(
        self,
        host: str = MAJSOUL_HOST,
        interval: float = DEFAULT_INTERVAL,
        client_version: Optional[str] = None,
    ):
        self.host = host.rstrip("/")
        self.interval = interval
        self._version: Optional[str] = None        # 服务端版本（如 0.11.252.w）
        self._client_version: Optional[str] = client_version  # 形如 web-0.11.252
        self._channel: Optional[MajsoulRPCChannel] = None
        self._last_request_at = 0.0
        self._token: Optional[str] = None

    # ---- 服务器发现 ----

    async def discover(self, timeout: float = 15.0) -> str:
        """发现并返回网关 wss 端点。"""
        version = await asyncio.to_thread(self._http_get_json, f"{self.host}/1/version.json", timeout)
        self._version = version["version"]
        self._client_version = self._client_version or (
            "web-" + self._version.replace(".w", "")
        )
        logger.info("雀魂版本: %s (client_version=%s)", self._version, self._client_version)

        cfg = await asyncio.to_thread(
            self._http_get_json, f"{self.host}/1/v{self._version}/config.json", timeout
        )
        ip0 = cfg["ip"][0]

        # 新版（国际服）：gateways 直连
        gateways = [g["url"] for g in ip0.get("gateways", [])]
        if gateways:
            endpoint = random.choice(gateways).replace("https://", "wss://") + "/gateway"
            logger.info("网关: %s", endpoint)
            return endpoint

        # 旧版/国服：region_urls -> 服务器列表
        region_urls = ip0.get("region_urls", [])
        if isinstance(region_urls, dict):
            region_urls = list(region_urls.values())
        for base in region_urls:
            try:
                servers = await asyncio.to_thread(
                    self._http_get_json,
                    f"{base}?service=ws-gateway&protocol=ws&ssl=true",
                    timeout,
                )
                if servers.get("servers"):
                    endpoint = f"wss://{random.choice(servers['servers'])}/gateway"
                    logger.info("网关: %s", endpoint)
                    return endpoint
            except Exception as exc:
                logger.warning("网关列表查询失败 %s: %s", base, exc)
        raise MajsoulError("未找到可用雀魂网关")

    # ---- 连接 ----

    async def connect(self, timeout: float = 15.0) -> None:
        if self._channel is not None:
            return
        endpoint = await self.discover(timeout)
        channel = MajsoulRPCChannel(endpoint, origin=self.host)
        await channel.connect(timeout)
        self._channel = channel

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None

    # ---- 登录 ----

    async def check_token(self, token: str, timeout: float = 15.0) -> bool:
        """校验 access_token 是否有效（oauth2Check）。"""
        await self.connect(timeout)
        req = pb.ReqOauth2Check()
        req.access_token = token
        data = await self._channel.call(".lq.Lobby.oauth2Check", req, timeout)
        res = pb.ResOauth2Check()
        res.ParseFromString(data)
        if res.error.code:
            raise _error_from_code(res.error.code)
        return res.has_account

    async def login_with_token(
        self, token: str, random_key: Optional[str] = None, timeout: float = 15.0,
        credentials: Optional[dict] = None,
    ) -> pb.ResLogin:
        """使用 access_token 建立登录会话。

        优先使用 credentials（浏览器登录请求的原样参数）完整复刻登录，
        保证 random_key/device/type 等与浏览器一致；否则退化为默认参数。

        登录链：oauth2Login（主）→ 失败回退 prepareLogin → loginSuccess 确认。

        Args:
            token: 从浏览器获取的 access_token
            random_key: 浏览器登录时的随机 key（可选；credentials 优先）
            credentials: 浏览器登录请求参数字典（token_helper 抓取）
            timeout: RPC 超时

        Returns:
            ResLogin（含 account_id、access_token 等）
        """
        await self.connect(timeout)

        method = (credentials or {}).get("method", ".lq.Lobby.oauth2Login")

        # ---- 1) 按浏览器原始方法登录 ----
        if method == ".lq.Lobby.prepareLogin":
            # 浏览器本身就用 prepareLogin：直接原样重放
            return await self._login_via_prepare(token, credentials, timeout)

        # 其余走 oauth2Login
        req = pb.ReqOauth2Login()
        req.access_token = token
        if credentials and credentials.get("raw") and method == ".lq.Lobby.oauth2Login":
            # 完整复刻浏览器请求（含 client_version/gen_access_token/version 等全部字段）
            try:
                raw_req = pb.ReqOauth2Login()
                raw_req.ParseFromString(base64.b64decode(credentials["raw"]))
                req = raw_req
                req.access_token = token  # 确保使用最新 token
                logger.info(
                    "oauth2Login: 原样重放浏览器请求（含 client_version/gen_access_token/version）"
                )
            except Exception as exc:
                logger.warning("重放原始请求失败，回退字段级复刻: %s", exc)
                req = _fill_login_req(req, token, credentials)
        elif credentials:
            req = _fill_login_req(req, token, credentials)
        else:
            req.device.is_browser = True
            req.device.platform = "pc"
            req.device.sale_platform = "majsoul"
            if random_key:
                req.random_key = random_key
            req.gen_access_token = True
            req.currency_platforms.append(2)
            if self._client_version:
                req.client_version_string = self._client_version

        try:
            data = await self._channel.call(".lq.Lobby.oauth2Login", req, timeout)
        except MajsoulAuthError as exc:
            # ---- 2) 回退：prepareLogin ----
            logger.warning("oauth2Login 失败(%s)，回退 prepareLogin", exc)
            return await self._login_via_prepare(token, credentials, timeout, oauth_error=exc)

        res = pb.ResLogin()
        res.ParseFromString(data)
        if res.error.code:
            raise _error_from_code(res.error.code, _error_detail(res.error))

        self._token = res.access_token or token
        await self._login_success(timeout)
        logger.info("登录成功: account_id=%s", res.account_id)
        return res

    async def _login_via_prepare(
        self,
        token: str,
        credentials: Optional[dict],
        timeout: float = 15.0,
        oauth_error: Optional[Exception] = None,
    ) -> pb.ResLogin:
        """通过 prepareLogin 登录（含原样重放）。"""
        preq = pb.ReqPrepareLogin()
        preq.access_token = token
        if credentials:
            if credentials.get("raw") and credentials.get("method") == ".lq.Lobby.prepareLogin":
                try:
                    raw_req = pb.ReqPrepareLogin()
                    raw_req.ParseFromString(base64.b64decode(credentials["raw"]))
                    preq = raw_req
                    preq.access_token = token
                    logger.info("prepareLogin: 原样重放浏览器请求")
                except Exception as exc:
                    logger.warning("prepareLogin 重放失败，字段级复刻: %s", exc)
            if credentials.get("type") is not None:
                preq.type = credentials["type"]
        try:
            pdata = await self._channel.call(".lq.Lobby.prepareLogin", preq, timeout)
            pres = pb.ResCommon()
            pres.ParseFromString(pdata)
            if pres.error.code:
                raise _error_from_code(pres.error.code, _error_detail(pres.error))
            self._token = token
            await self._login_success(timeout)
            logger.info("prepareLogin 登录成功（token 模式）")
            return pb.ResLogin(access_token=token)
        except MajsoulError as pexc:
            if oauth_error is not None:
                raise MajsoulAuthError(
                    f"token 登录失败（oauth2Login={oauth_error}，prepareLogin={pexc}）。"
                    "请重新导入 access_token（确认浏览器已登录）。"
                ) from None
            raise

    async def _login_success(self, timeout: float = 15.0) -> None:
        """登录成功后通知服务器（某些版本 fetchGameRecord 依赖该状态）。"""
        try:
            await self._channel.call(".lq.Lobby.loginSuccess", pb.ReqCommon(), timeout)
        except Exception as exc:
            logger.warning("loginSuccess 调用失败（不致命）: %s", exc)

    async def login_with_account(
        self, account: str, password: str, timeout: float = 15.0
    ) -> pb.ResLogin:
        """账号密码登录（可能被风控拒绝，错误码 151）。"""
        await self.connect(timeout)
        req = pb.ReqLogin()
        req.account = account
        req.password = hmac.new(
            b"lailai", password.encode(), hashlib.sha256
        ).hexdigest()
        req.device.is_browser = True
        req.device.platform = "pc"
        req.random_key = str(uuid.uuid1())
        req.gen_access_token = True
        req.currency_platforms.append(2)
        if self._client_version:
            req.client_version_string = self._client_version

        data = await self._channel.call(".lq.Lobby.login", req, timeout)
        res = pb.ResLogin()
        res.ParseFromString(data)
        if res.error.code:
            raise _error_from_code(res.error.code, _error_detail(res.error))
        self._token = res.access_token
        logger.info("登录成功: account_id=%s", res.account_id)
        return res

    # ---- 牌谱拉取 ----

    async def fetch_game_record(
        self, uuid: str, timeout: float = 60.0
    ) -> pb.ResGameRecord:
        """拉取单条牌谱（fetchGameRecord），返回 ResGameRecord。

        未登录会话会收到错误码 1004（MajsoulNotLoggedInError）。
        """
        await self._throttle()
        await self.connect(timeout)

        req = pb.ReqGameRecord()
        req.game_uuid = uuid
        if self._client_version:
            req.client_version_string = self._client_version

        data = await self._channel.call(".lq.Lobby.fetchGameRecord", req, timeout)
        res = pb.ResGameRecord()
        res.ParseFromString(data)
        if res.error.code:
            raise _error_from_code(res.error.code, _error_detail(res.error))
        return res

    async def fetch_paipu(self, uuid: str, timeout: float = 60.0) -> bytes:
        """拉取牌谱并返回 GameDetailRecords 数据字节。

        若响应为 data_url 形式，自动异步下载补全。
        """
        res = await self.fetch_game_record(uuid, timeout)
        if res.data:
            return bytes(res.data)
        if res.data_url:
            logger.info("data_url 拉取: %s", res.data_url)
            raw = await asyncio.to_thread(self._http_get, res.data_url, timeout)
            return raw
        raise MajsoulError(f"牌谱 {uuid} 响应中无 data 也无 data_url")

    # ---- 内部工具 ----

    async def _throttle(self) -> None:
        """连续请求间隔控制（风控保护）。"""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _http_get(url: str, timeout: float = 30.0) -> bytes:
        import urllib.request

        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Referer": MAJSOUL_HOST}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    @classmethod
    def _http_get_json(cls, url: str, timeout: float = 30.0) -> Dict[str, Any]:
        return json.loads(cls._http_get(url, timeout).decode("utf-8"))


# ---------------------------------------------------------------------------
# 顶层便捷接口
# ---------------------------------------------------------------------------


async def download_paipu(
    uuid: str,
    token: Optional[str] = None,
    host: str = MAJSOUL_HOST,
    interval: float = DEFAULT_INTERVAL,
) -> bytes:
    """一步到位拉取牌谱数据（GameDetailRecords 字节）。

    Args:
        uuid: 对局唯一 ID（url_parser 解析结果）
        token: 可选 access_token（未提供时以未登录会话尝试，可能被拒）
        host: 雀魂服务器地址
        interval: 请求间隔（秒）

    Returns:
        GameDetailRecords 序列化字节，可直接交给 proto.decoder.decode_paipu
    """
    client = MajsoulClient(host=host, interval=interval)
    try:
        if token:
            await client.login_with_token(token)
        return await client.fetch_paipu(uuid)
    finally:
        await client.close()


def download_paipu_sync(
    uuid: str,
    token: Optional[str] = None,
    host: str = MAJSOUL_HOST,
    interval: float = DEFAULT_INTERVAL,
) -> bytes:
    """同步版 download_paipu（供 CLI / FastAPI 直接调用）。"""
    return asyncio.run(download_paipu(uuid, token, host, interval))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="雀魂牌谱拉取（阶段二）")
    parser.add_argument("uuid", help="对局唯一 ID（或完整牌谱链接）")
    parser.add_argument("--token", help="access_token（从浏览器获取）")
    parser.add_argument("--out", help="输出文件（默认 stdout 存 _paipu.bin）")
    parser.add_argument("--host", default=MAJSOUL_HOST)
    args = parser.parse_args()

    uuid_str = args.uuid
    if "paipu=" in uuid_str:
        from url_parser import parse_paipu_url

        uuid_str = parse_paipu_url(uuid_str, check_host=False).uuid

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        data = download_paipu_sync(uuid_str, token=args.token, host=args.host)
    except MajsoulAuthError as exc:
        print(f"认证失败: {exc}")
        print("提示：请配置 access_token（见 README「获取 access_token」）。")
        sys.exit(2)
    except MajsoulNotLoggedInError as exc:
        print(f"拉取失败: {exc}")
        sys.exit(3)

    out = args.out or "_paipu.bin"
    with open(out, "wb") as f:
        f.write(data)
    print(f"已保存 {len(data)} 字节 -> {out}")


if __name__ == "__main__":
    _main()
