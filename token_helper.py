"""雀魂 access_token 一键导入辅助（阶段二·登录辅助）。

通过 CDP（Chrome DevTools Protocol）连接本地调试浏览器
（Edge / Chrome，需以 --remote-debugging-port=9222 启动），
复用浏览器中已有的雀魂登录态：

    1. 找到/打开雀魂页面（game.maj-soul.com）
    2. 刷新页面，Unity 前端会自动重新 login
    3. 监听 WebSocket 帧中的 login 响应（type=3 RESPONSE）
    4. 从 ResLogin 中提取 access_token

无需安装浏览器扩展、无需信任证书、无中间人代理。

用法：
    import token_helper
    token = await token_helper.import_token()   # 连接 9222 端口
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import websockets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto"))
import protocol_pb2 as pb  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORT = 9222
MAJSOUL_URL = "https://game.maj-soul.com/1/"
TIMEOUT = 120.0  # 等待 login 帧的超时（秒，Unity WebGL 加载较慢）

# WebSocket 帧类型（与 majsoul_ws 一致）
TYPE_NOTIFY = 1
TYPE_REQUEST = 2
TYPE_RESPONSE = 3


class TokenImportError(Exception):
    """token 导入失败。"""


# ---------------------------------------------------------------------------
# CDP 客户端
# ---------------------------------------------------------------------------


class CDPClient:
    """极简 CDP 客户端（仅实现本工具所需子集）。"""

    def __init__(self, port: int = DEFAULT_CDP_PORT):
        self.port = port
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._msg_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        # 帧监听：请求帧 hook(payload_data, idx, method)，响应帧 hook(payload_data, method, request_id)
        self._sent_hooks: List[Any] = []
        self._recv_hooks: List[Any] = []
        # 请求号 -> RPC 方法名（用于把响应匹配回请求）
        self._req_methods: Dict[int, str] = {}

    # ---- HTTP 辅助 ----

    @staticmethod
    def _http_get(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers={"User-Agent": "dsh-majong"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def version(self) -> Dict[str, Any]:
        return self._http_get(f"http://127.0.0.1:{self.port}/json/version")

    def list_targets(self) -> List[Dict[str, Any]]:
        return self._http_get(f"http://127.0.0.1:{self.port}/json/list")

    # ---- WS 连接 ----

    async def connect(self) -> None:
        info = await asyncio.to_thread(self.version)
        ws_url = info.get("webSocketDebuggerUrl")
        if not ws_url:
            raise TokenImportError("CDP 端点未返回 webSocketDebuggerUrl")
        self._ws = await websockets.connect(ws_url, open_timeout=10)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            await self._ws.close()

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    params = msg.get("params", {})
                    response = params.get("response", {})
                    payload = response.get("payloadData", "")
                    request_id = params.get("requestId", "")
                    if msg["method"] == "Network.webSocketFrameSent":
                        req = _parse_request_frame(payload)
                        if req is not None:
                            idx, name = req
                            self._req_methods[idx] = name
                            for hook in list(self._sent_hooks):
                                try:
                                    hook(payload, idx, name)
                                except Exception as exc:
                                    logger.warning("sent hook 异常: %s", exc)
                    elif msg["method"] == "Network.webSocketFrameReceived":
                        idx, method = _parse_response_idx(payload, self._req_methods)
                        for hook in list(self._recv_hooks):
                            try:
                                hook(payload, method, request_id, idx)
                            except Exception as exc:
                                logger.warning("recv hook 异常: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("CDP 接收循环退出: %s", exc)

    async def send(self, method: str, params: Optional[Dict] = None, session_id: Optional[str] = None) -> Dict:
        assert self._ws is not None
        self._msg_id += 1
        msg: Dict[str, Any] = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._msg_id] = fut
        await self._ws.send(json.dumps(msg))
        resp = await asyncio.wait_for(fut, timeout=30)
        if "error" in resp:
            raise TokenImportError(f"CDP 方法 {method} 失败: {resp['error']}")
        return resp.get("result", {})

    # ---- 目标管理 ----

    async def find_or_create_page(self) -> str:
        """找到雀魂页面 target，不存在则创建。返回 targetId。"""
        targets = await asyncio.to_thread(self.list_targets)
        for t in targets:
            if t.get("type") == "page" and (
                "maj-soul.com" in t.get("url", "") or "majsoul.com" in t.get("url", "")
            ):
                logger.info("找到雀魂页面: %s", t.get("url"))
                return t["id"]
        result = await self.send(
            "Target.createTarget", {"url": MAJSOUL_URL, "newWindow": False}
        )
        target_id = result["targetId"]
        logger.info("已创建雀魂页面 target: %s", target_id)
        return target_id

    async def attach(self, target_id: str) -> str:
        result = await self.send(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        return result["sessionId"]

    def add_sent_hook(self, hook) -> None:
        """注册请求帧监听：hook(payload_data, idx, method)。"""
        self._sent_hooks.append(hook)

    def add_recv_hook(self, hook) -> None:
        """注册响应帧监听：hook(payload_data, matched_method, request_id)。"""
        self._recv_hooks.append(hook)


# ---------------------------------------------------------------------------
# 帧解析与 token 提取
# ---------------------------------------------------------------------------


def _parse_request_frame(payload_data: str) -> Optional[tuple]:
    """解析 REQUEST 帧（type=2），返回 (idx, 方法名)；非请求帧返回 None。"""
    if not payload_data:
        return None
    try:
        raw = base64.b64decode(payload_data)
    except Exception:
        return None
    if not raw or raw[0] != TYPE_REQUEST:
        return None
    idx = int.from_bytes(raw[1:3], "little")
    w = pb.Wrapper()
    try:
        w.ParseFromString(raw[3:])
    except Exception:
        return None
    return idx, w.name


def _match_response_method(payload_data: str, req_methods: Dict[int, str]) -> Optional[str]:
    """按请求号把 RESPONSE 帧匹配回方法名；匹配不到返回 None。"""
    idx, _ = _parse_response_idx(payload_data, req_methods)
    return req_methods.get(idx) if idx is not None else None


def _parse_response_idx(payload_data: str, req_methods: Dict[int, str]) -> tuple:
    """解析 RESPONSE 帧的请求号与方法名，返回 (idx, method)。"""
    if not payload_data:
        return None, None
    try:
        raw = base64.b64decode(payload_data)
    except Exception:
        return None, None
    if not raw or raw[0] != TYPE_RESPONSE:
        return None, None
    idx = int.from_bytes(raw[1:3], "little")
    return idx, req_methods.get(idx)


def parse_response_wrapper(payload_data: str) -> Optional[pb.Wrapper]:
    """将 CDP 帧负载解析为 Wrapper（仅处理 type=3 RESPONSE 帧）。

    payloadData 对二进制帧为 base64 字符串。
    """
    if not payload_data:
        return None
    try:
        raw = base64.b64decode(payload_data)
    except Exception:
        return None
    if not raw or raw[0] != TYPE_RESPONSE:
        return None
    body = raw[3:]
    w = pb.Wrapper()
    try:
        w.ParseFromString(body)
    except Exception:
        return None
    return w


def extract_access_token(wrapper: pb.Wrapper) -> Optional[str]:
    """从响应 Wrapper 中提取 access_token（尝试 ResLogin / ResOauth2Login）。"""
    if not wrapper.data:
        return None
    res = pb.ResLogin()
    try:
        res.ParseFromString(wrapper.data)
    except Exception:
        return None
    return res.access_token or None


# 登录类 RPC 方法
LOGIN_METHODS = {
    ".lq.Lobby.login",
    ".lq.Lobby.oauth2Login",
    ".lq.Lobby.prepareLogin",
}

# 需复刻的设备字段
_DEVICE_FIELDS = (
    "platform", "hardware", "os", "os_version", "is_browser",
    "software", "sale_platform", "hardware_vendor", "model_number",
    "screen_width", "screen_height", "user_agent", "screen_type",
)


def _device_to_dict(device) -> Dict[str, Any]:
    """将 ClientDeviceInfo 序列化为 dict（仅保留非默认值字段）。"""
    out: Dict[str, Any] = {}
    for f in _DEVICE_FIELDS:
        v = getattr(device, f)
        if v:  # 非空 / 非 0 / 非 False（proto3 标量无 presence）
            out[f] = v
    return out


def parse_login_request(payload_data: str) -> Optional[dict]:
    """解析登录类 REQUEST 帧，返回可重放的参数字典；非登录请求返回 None。

    返回结构（credentials）：
        {"method": str, "raw": base64(请求消息完整字节), "type": int|None,
         "random_key": str|None, "client_version_string": str|None,
         "device": dict|None, "currency_platforms": list[int],
         "reconnect": bool|None, "tag": str|None,
         "client_version": dict|None, "gen_access_token": bool|None,
         "version": int|None}
    """
    if not payload_data:
        return None
    try:
        raw = base64.b64decode(payload_data)
    except Exception:
        return None
    if not raw or raw[0] != TYPE_REQUEST:
        return None
    w = pb.Wrapper()
    try:
        w.ParseFromString(raw[3:])
    except Exception:
        return None
    name = w.name
    if name not in LOGIN_METHODS:
        return None

    common = {
        "method": name,
        "raw": base64.b64encode(w.data).decode(),  # 请求消息完整字节，登录时原样重放
        "type": None,
        "random_key": None,
        "client_version_string": None,
        "device": None,
        "currency_platforms": [],
        "reconnect": None,
        "tag": None,
        "client_version": None,
        "gen_access_token": None,
        "version": None,
    }
    try:
        if name == ".lq.Lobby.oauth2Login":
            req = pb.ReqOauth2Login()
            req.ParseFromString(w.data)
            common.update(
                type=req.type or None,
                random_key=req.random_key or None,
                client_version_string=req.client_version_string or None,
                currency_platforms=list(req.currency_platforms),
                reconnect=req.reconnect,
                tag=req.tag or None,
                gen_access_token=req.gen_access_token,
                version=req.version or None,
            )
            if req.HasField("device"):
                common["device"] = _device_to_dict(req.device)
            if req.HasField("client_version"):
                cv = req.client_version
                common["client_version"] = {
                    k: v for k, v in (
                        ("resource", cv.resource), ("package", cv.package)
                    ) if v
                }
        elif name == ".lq.Lobby.login":
            req = pb.ReqLogin()
            req.ParseFromString(w.data)
            common.update(
                type=req.type or None,
                random_key=req.random_key or None,
                client_version_string=req.client_version_string or None,
                currency_platforms=list(req.currency_platforms),
                reconnect=req.reconnect,
                tag=req.tag or None,
                gen_access_token=req.gen_access_token,
                version=req.version or None,
            )
            if req.HasField("device"):
                common["device"] = _device_to_dict(req.device)
            if req.HasField("client_version"):
                cv = req.client_version
                common["client_version"] = {
                    k: v for k, v in (
                        ("resource", cv.resource), ("package", cv.package)
                    ) if v
                }
        elif name == ".lq.Lobby.prepareLogin":
            req = pb.ReqPrepareLogin()
            req.ParseFromString(w.data)
            common["type"] = req.type or None
    except Exception as exc:
        logger.warning("登录请求解析失败 %s: %s", name, exc)
        return None
    return common


# ---------------------------------------------------------------------------
# 浏览器定位与启动
# ---------------------------------------------------------------------------


def find_browser() -> Optional[str]:
    """查找本机 Edge / Chrome 可执行文件路径。"""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    # PATH 兜底
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def launch_browser(
    port: int = DEFAULT_CDP_PORT,
    profile_dir: Optional[str] = None,
    url: str = MAJSOUL_URL,
) -> str:
    """以调试模式启动浏览器，返回可执行文件路径。

    注意：必须使用独立的 --user-data-dir，否则已运行的浏览器实例
    会吞掉 --remote-debugging-port 参数。
    """
    exe = find_browser()
    if not exe:
        raise TokenImportError("未找到 Edge/Chrome，请手动启动调试浏览器")
    profile = profile_dir or str(Path(__file__).resolve().parent / ".browser-profile")
    Path(profile).mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        url,
    ]
    # 使用 DEVNULL 而非管道，避免子进程输出捕获在受限环境被拒
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    logger.info("已启动调试浏览器: %s (port=%s)", exe, port)
    return exe


# ---------------------------------------------------------------------------
# 一键导入
# ---------------------------------------------------------------------------


async def wait_cdp_ready(port: int = DEFAULT_CDP_PORT, timeout: float = 20.0) -> bool:
    """等待 CDP 端口就绪。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            await asyncio.to_thread(CDPClient._http_get, f"http://127.0.0.1:{port}/json/version")
            return True
        except Exception:
            await asyncio.sleep(0.5)
    return False


async def import_token(
    port: int = DEFAULT_CDP_PORT,
    timeout: float = TIMEOUT,
    reload: bool = True,
) -> Dict[str, Any]:
    """从调试浏览器导入雀魂 access_token 与登录参数。

    Args:
        port: CDP 调试端口
        timeout: 等待 login 帧超时（秒）
        reload: 是否刷新雀魂页面触发重新登录

    Returns:
        {"access_token": str, "credentials": {...}}——
        credentials 为浏览器登录请求的原样参数（random_key/type/device 等），
        供登录时完整复刻。

    Raises:
        TokenImportError: 连接失败 / 未登录 / 超时
    """
    if not await wait_cdp_ready(port):
        raise TokenImportError(
            f"CDP 端口 {port} 不可用。请先用调试模式启动浏览器：\n"
            f"  {find_browser() or 'Edge/Chrome'} --remote-debugging-port={port} "
            "--user-data-dir=<独立目录> https://game.maj-soul.com/1/"
        )

    client = CDPClient(port)
    holder: Dict[str, Any] = {"token": None, "credentials": None, "req_params": {}}

    def on_request(payload_data: str, idx: int, method: str) -> None:
        # 捕获登录请求参数（random_key 等），按请求号保存，供响应配套
        if method not in LOGIN_METHODS:
            return
        params = parse_login_request(payload_data)
        if params:
            holder["req_params"][idx] = params
            logger.info(
                "已捕获登录请求: method=%s idx=%s random_key=%s type=%s",
                method, idx, bool(params.get("random_key")), params.get("type"),
            )

    def on_response(
        payload_data: str, matched_method: Optional[str], request_id: str, idx: Optional[int]
    ) -> None:
        if matched_method is not None and matched_method not in LOGIN_METHODS:
            return
        wrapper = parse_response_wrapper(payload_data)
        if wrapper is None:
            return
        # 兜底：方法匹配不到时，仅接受显式 ResLogin 命名响应
        if matched_method is None and wrapper.name != ".lq.ResLogin":
            return
        token = extract_access_token(wrapper)
        if token and holder["token"] is None:
            holder["token"] = token
            # 配套：同一请求号的登录参数（token 与 random_key 严格同源）
            credentials = holder["req_params"].get(idx) if idx is not None else None
            holder["credentials"] = credentials
            logger.info(
                "已捕获 access_token（长度 %d，来源 %s，配套登录参数=%s）",
                len(token), matched_method or wrapper.name,
                "是" if credentials else "否",
            )

    client.add_sent_hook(on_request)
    client.add_recv_hook(on_response)

    try:
        await client.connect()
        target_id = await client.find_or_create_page()
        session_id = await client.attach(target_id)
        await client.send("Network.enable", session_id=session_id)
        await client.send("Page.enable", session_id=session_id)

        if reload:
            await client.send("Page.reload", {"ignoreCache": True}, session_id=session_id)

        # 等待 token 或超时
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if holder["token"]:
                return {
                    "access_token": holder["token"],
                    "credentials": holder["credentials"],
                }
            await asyncio.sleep(0.5)
    finally:
        await client.close()

    raise TokenImportError(
        "未捕获到 login 响应。请确认："
        "① 调试浏览器中已登录雀魂账号（game.maj-soul.com）；"
        "② 页面已完成加载；然后重试（刷新页面触发重新登录）。"
    )


def import_token_sync(port: int = DEFAULT_CDP_PORT, timeout: float = TIMEOUT) -> Dict[str, Any]:
    """同步版 import_token（供 FastAPI 调用）。"""
    return asyncio.run(import_token(port=port, timeout=timeout))


# ---------------------------------------------------------------------------
# 浏览器捕获牌谱（无需 token：让浏览器自己拉牌谱，我们截获响应帧）
# ---------------------------------------------------------------------------


class CaptureRecordError(Exception):
    """浏览器捕获牌谱失败。"""


def _is_game_record_data(wrapper: pb.Wrapper) -> Optional[pb.ResGameRecord]:
    """判断响应 Wrapper.data 是否为 ResGameRecord（含 head+data/data_url）。"""
    if not wrapper.data:
        return None
    res = pb.ResGameRecord()
    try:
        res.ParseFromString(wrapper.data)
    except Exception:
        return None
    if not (res.HasField("head") or res.head.uuid):
        return None
    if not (res.data or res.data_url):
        return None
    return res


async def capture_game_record(
    paipu_url: str,
    port: int = DEFAULT_CDP_PORT,
    timeout: float = 180.0,
) -> bytes:
    """通过调试浏览器打开牌谱链接，捕获浏览器自动拉取的牌谱数据。

    原理：雀魂网页端在登录后打开牌谱链接会自动调用 fetchGameRecord；
    我们通过 CDP 打开链接并监听 WebSocket 响应帧，截获 ResGameRecord，
    返回其 data 字段（GameDetailRecords 外层 Wrapper 字节）。

    Args:
        paipu_url: 完整雀魂牌谱链接
        port: CDP 调试端口
        timeout: 等待响应超时（秒，Unity 加载较慢）

    Returns:
        ResGameRecord.data 字节（可直接交给 proto.decoder.decode_paipu）

    Raises:
        CaptureRecordError: CDP 不可用 / 未登录 / 超时 / 牌谱拉取失败
    """
    if not await wait_cdp_ready(port):
        raise CaptureRecordError(
            f"CDP 端口 {port} 不可用，请先用「启动调试浏览器」打开并登录雀魂。"
        )

    client = CDPClient(port)
    holder: Dict[str, Any] = {"result": None, "fetch_idx": None}

    def on_request(payload_data: str, idx: int, method: str) -> None:
        if method == ".lq.Lobby.fetchGameRecord":
            holder["fetch_idx"] = idx
            logger.info("检测到 fetchGameRecord 请求（idx=%s）", idx)

    def on_response(
        payload_data: str, matched_method: Optional[str], request_id: str, idx: Optional[int]
    ) -> None:
        # 只处理 fetchGameRecord 的响应（请求号匹配；必要时按 ResGameRecord 特征兜底）
        if holder["fetch_idx"] is not None and idx != holder["fetch_idx"]:
            return
        wrapper = parse_response_wrapper(payload_data)
        if wrapper is None:
            return
        res = _is_game_record_data(wrapper)
        if res is None:
            return
        if res.error.code:
            holder["result"] = ("error", res.error)
            return
        holder["result"] = ("ok", bytes(res.data or b""))
        logger.info("已捕获牌谱数据（%d 字节）", len(res.data))

    client.add_sent_hook(on_request)
    client.add_recv_hook(on_response)

    try:
        await client.connect()
        target_id = await client.find_or_create_page()
        session_id = await client.attach(target_id)
        await client.send("Network.enable", session_id=session_id)
        await client.send("Page.enable", session_id=session_id)

        # 打开牌谱链接（会触发浏览器 fetchGameRecord）
        logger.info("浏览器打开牌谱链接: %s", paipu_url)
        await client.send("Page.navigate", {"url": paipu_url}, session_id=session_id)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if holder["result"] is not None:
                kind, payload = holder["result"]
                if kind == "ok":
                    return payload
                # 业务错误（如 1004/151）
                raise CaptureRecordError(f"浏览器拉取牌谱失败：code={payload.code}")
            await asyncio.sleep(0.5)
    finally:
        await client.close()

    raise CaptureRecordError(
        "未捕获到 fetchGameRecord 响应。请确认："
        "① 调试浏览器中已登录雀魂账号；"
        "② 页面能正常打开牌谱链接（手动粘贴链接到浏览器试试）；"
        "然后重试。"
    )


async def close_browser(port: int = DEFAULT_CDP_PORT, timeout: float = 3.0) -> bool:
    """通过 CDP 优雅关闭调试浏览器。

    Returns:
        True 表示已发送关闭请求（或浏览器本来就没开）；False 表示关闭失败。
    """
    if not await wait_cdp_ready(port, timeout=min(timeout, 2.0)):
        return True  # 浏览器未运行，视为已关闭
    client = CDPClient(port)
    try:
        await client.connect()
        # Browser.close 发出后浏览器立即关闭，不等响应（避免 30s 超时）
        await client._ws.send(json.dumps({"id": 99999, "method": "Browser.close"}))
        await asyncio.sleep(1.0)
        logger.info("已请求调试浏览器关闭（port=%s）", port)
        return True
    except Exception as exc:
        logger.warning("浏览器关闭失败: %s", exc)
        return False
    finally:
        await client.close()


def close_browser_sync(port: int = DEFAULT_CDP_PORT) -> bool:
    """同步版 close_browser。"""
    return asyncio.run(close_browser(port=port))


# ---------------------------------------------------------------------------
# .env 写入
# ---------------------------------------------------------------------------


def build_env_content(existing: str, key: str, value: str) -> str:
    """纯函数：在现有 .env 文本中更新/追加 `key=value`。"""
    lines = existing.splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    return "\n".join(lines)


def save_token_to_env(token: str, env_path: Optional[Path] = None) -> Path:
    """将 token 写入/更新项目 .env 的 DSH_MAJONG_MAJSOUL_TOKEN。"""
    path = env_path or (Path(__file__).resolve().parent / ".env")
    content = ""
    if path.exists():
        content = path.read_text(encoding="utf-8")
    content = build_env_content(content, "DSH_MAJONG_MAJSOUL_TOKEN", token)
    path.write_text(content + "\n", encoding="utf-8")
    logger.info("token 已写入 %s", path)
    return path


def mask_token(token: str) -> str:
    """脱敏展示：保留前 6 位与后 4 位。"""
    if len(token) <= 12:
        return token[:3] + "***"
    return f"{token[:6]}...{token[-4:]}"


# ---------------------------------------------------------------------------
# 登录参数（credentials）存取
# ---------------------------------------------------------------------------


def credentials_path() -> Path:
    """登录参数文件路径（含 random_key/device 等敏感信息，勿入库）。"""
    return Path(__file__).resolve().parent / "majsoul_credentials.json"


def save_credentials(credentials: dict, path: Optional[Path] = None) -> Path:
    """保存登录参数（与 token 配套，登录时原样重放）。"""
    p = path or credentials_path()
    p.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("登录参数已保存: %s", p)
    return p


def load_credentials(path: Optional[Path] = None) -> Optional[dict]:
    """读取登录参数；不存在或损坏返回 None。"""
    p = path or credentials_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("登录参数文件读取失败 %s: %s", p, exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        tok = import_token_sync()
        save_token_to_env(tok)
        print(f"成功！access_token 已保存到 .env（{mask_token(tok)}）")
    except TokenImportError as exc:
        print(f"导入失败：{exc}")
        sys.exit(1)
