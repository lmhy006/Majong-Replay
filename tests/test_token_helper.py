"""token_helper 单元测试（阶段二·登录辅助）。

帧解析与 token 提取为纯函数测试；CDP 交互流程用 FakeCDP mock；
另有 FakeCDPServer 端到端验证（真实 HTTP+WS 模拟 CDP 协议）。
"""

import asyncio
import base64
import json
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

import protocol_pb2 as pb  # noqa: E402
import token_helper  # noqa: E402
from token_helper import (  # noqa: E402
    TokenImportError,
    extract_access_token,
    mask_token,
    parse_response_wrapper,
    save_token_to_env,
)


def make_login_frame(token: str) -> str:
    """构造一个含 access_token 的 login RESPONSE 帧（base64，idx=7）。"""
    res = pb.ResLogin()
    res.access_token = token
    w = pb.Wrapper()
    w.name = ".lq.ResLogin"
    w.data = res.SerializeToString()
    raw = b"\x03" + (7).to_bytes(2, "little") + w.SerializeToString()
    return base64.b64encode(raw).decode()


def make_discard_frame() -> str:
    """构造一个非 login 的 RESPONSE 帧（打牌事件）。"""
    rec = pb.RecordDiscardTile()
    rec.seat = 1
    rec.tile = "1m"
    w = pb.Wrapper()
    w.name = ".lq.RecordDiscardTile"
    w.data = rec.SerializeToString()
    raw = b"\x03" + (2).to_bytes(2, "little") + w.SerializeToString()
    return base64.b64encode(raw).decode()


class TestParseResponseWrapper(unittest.TestCase):
    def test_valid_login_frame(self):
        w = parse_response_wrapper(make_login_frame("tok123"))
        self.assertIsNotNone(w)
        self.assertEqual(w.name, ".lq.ResLogin")

    def test_non_response_frame_ignored(self):
        # NOTIFY 帧（type=1）
        notify = b"\x01" + pb.Wrapper().SerializeToString()
        self.assertIsNone(parse_response_wrapper(base64.b64encode(notify).decode()))

    def test_garbage_ignored(self):
        self.assertIsNone(parse_response_wrapper("not-base64!!"))
        self.assertIsNone(parse_response_wrapper(""))


class TestExtractAccessToken(unittest.TestCase):
    def test_extract_from_login(self):
        w = parse_response_wrapper(make_login_frame("secret-token"))
        self.assertEqual(extract_access_token(w), "secret-token")

    def test_non_login_response_none(self):
        w = parse_response_wrapper(make_discard_frame())
        self.assertIsNone(extract_access_token(w))


class TestMaskToken(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask_token("abcdef1234567890"), "abcdef...7890")
        self.assertNotIn("123456", mask_token("abcdef1234567890"))
        self.assertEqual(mask_token("short"), "sho***")


class TestSaveTokenToEnv(unittest.TestCase):
    def test_create_new_env(self):
        content = token_helper.build_env_content("", "DSH_MAJONG_MAJSOUL_TOKEN", "tokA")
        self.assertIn("DSH_MAJONG_MAJSOUL_TOKEN=tokA", content)

    def test_update_existing_env(self):
        existing = "DSH_MAJONG_HOST=127.0.0.1\nDSH_MAJONG_MAJSOUL_TOKEN=old\n"
        content = token_helper.build_env_content(existing, "DSH_MAJONG_MAJSOUL_TOKEN", "tokB")
        self.assertIn("DSH_MAJONG_MAJSOUL_TOKEN=tokB", content)
        self.assertNotIn("=old", content)
        self.assertIn("DSH_MAJONG_HOST=127.0.0.1", content)

    def test_save_writes_file(self):
        # 写盘路径（沙箱内可能被拒，此处仅验证函数可用性：
        # 若环境允许写则验证内容；不允许则跳过）
        import os

        tmp = ROOT / ".test_tmp_env_write"
        try:
            path = tmp / ".env"
            path.parent.mkdir(parents=True, exist_ok=True)
            save_token_to_env("tokX", path)
            self.assertIn("DSH_MAJONG_MAJSOUL_TOKEN=tokX", path.read_text(encoding="utf-8"))
        except PermissionError:
            pass  # 沙箱限制写盘时跳过
        finally:
            try:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


class _FakeWS:
    def __init__(self):
        self.messages = []

    async def send(self, data):
        self.messages.append(data)


class FakeCDP:
    """mock CDPClient：Network.enable 时立即喂入预置帧。"""

    def __init__(self, port, mode="login"):
        self.port = port
        self.mode = mode
        self.sent_hooks = []
        self.recv_hooks = []
        self.frame = None
        self._ws = _FakeWS()

    async def connect(self):
        pass

    async def close(self):
        pass

    async def find_or_create_page(self):
        return "target-1"

    async def attach(self, target_id):
        return "session-1"

    async def send(self, method, params=None, session_id=None):
        if method == "Network.enable" and self.frame:
            if self.mode == "record":
                # 模拟浏览器拉取牌谱
                for h in list(self.sent_hooks):
                    h(_record_request_b64(7), 7, ".lq.Lobby.fetchGameRecord")
                for h in list(self.recv_hooks):
                    h(self.frame, ".lq.Lobby.fetchGameRecord", "req-1", 7)
            else:
                # 模拟登录
                for h in list(self.sent_hooks):
                    h(_login_request_b64(7), 7, ".lq.Lobby.login")
                for h in list(self.recv_hooks):
                    h(self.frame, ".lq.Lobby.login", "req-1", 7)
        return {}

    def add_sent_hook(self, hook):
        self.sent_hooks.append(hook)

    def add_recv_hook(self, hook):
        self.recv_hooks.append(hook)


def _login_request_b64(idx: int) -> str:
    """构造 login REQUEST 帧（type=2）base64。"""
    w = pb.Wrapper()
    w.name = ".lq.Lobby.login"
    w.data = b""
    raw = b"\x02" + idx.to_bytes(2, "little") + w.SerializeToString()
    return base64.b64encode(raw).decode()


def _record_request_b64(idx: int) -> str:
    """构造 fetchGameRecord REQUEST 帧（type=2）base64。"""
    w = pb.Wrapper()
    w.name = ".lq.Lobby.fetchGameRecord"
    w.data = b""
    raw = b"\x02" + idx.to_bytes(2, "little") + w.SerializeToString()
    return base64.b64encode(raw).decode()


def make_game_record_frame(data: bytes, idx: int = 7) -> str:
    """构造含 ResGameRecord 的 RESPONSE 帧（base64）。"""
    res = pb.ResGameRecord()
    res.head.uuid = "test-uuid"
    res.data = data
    w = pb.Wrapper()
    w.name = ".lq.ResGameRecord"
    w.data = res.SerializeToString()
    raw = b"\x03" + idx.to_bytes(2, "little") + w.SerializeToString()
    return base64.b64encode(raw).decode()


class TestImportToken(unittest.TestCase):
    def test_success(self):
        cdp = FakeCDP(9222)
        cdp.frame = make_login_frame("captured-token")

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            result = asyncio.run(token_helper.import_token(timeout=10))
        self.assertEqual(result["access_token"], "captured-token")
        # FakeCDP 同时喂了 login 请求帧，应捕获到登录参数
        self.assertIsNotNone(result.get("credentials"))
        self.assertEqual(result["credentials"]["method"], ".lq.Lobby.login")

    def test_timeout_raises(self):
        cdp = FakeCDP(9222)  # 不喂帧

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            with self.assertRaises(TokenImportError):
                asyncio.run(token_helper.import_token(timeout=0.3))

    def test_cdp_not_ready(self):
        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=False):
            with self.assertRaises(TokenImportError):
                asyncio.run(token_helper.import_token(timeout=5))


class TestParseLoginRequest(unittest.TestCase):
    def _oauth2_login_request(self, random_key: str, type_: int) -> str:
        req = pb.ReqOauth2Login()
        req.access_token = "tok"
        req.random_key = random_key
        req.type = type_
        req.device.is_browser = True
        req.device.platform = "pc"
        w = pb.Wrapper()
        w.name = ".lq.Lobby.oauth2Login"
        w.data = req.SerializeToString()
        raw = b"\x02" + (1).to_bytes(2, "little") + w.SerializeToString()
        return base64.b64encode(raw).decode()

    def test_parse_oauth2_login(self):
        frame = self._oauth2_login_request("rk-123", 1)
        params = token_helper.parse_login_request(frame)
        self.assertIsNotNone(params)
        self.assertEqual(params["method"], ".lq.Lobby.oauth2Login")
        self.assertEqual(params["random_key"], "rk-123")
        self.assertEqual(params["type"], 1)
        self.assertEqual(params["device"], {"is_browser": True, "platform": "pc"})

    def test_non_login_frame_none(self):
        self.assertIsNone(token_helper.parse_login_request(make_discard_frame()))

    def test_garbage_none(self):
        self.assertIsNone(token_helper.parse_login_request("not-base64"))


# ---------------------------------------------------------------------------
# 端到端：FakeCDPServer 模拟真实 CDP 协议（HTTP + WebSocket）
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeCDPServer:
    """模拟 CDP：HTTP 端点返回 version/list，WS 端点处理命令并发 login 帧事件。"""

    def __init__(self, http_port: int, ws_port: int, frame_b64: str):
        self.http_port = http_port
        self.ws_port = ws_port
        self.frame = frame_b64
        self._http: ThreadingHTTPServer | None = None
        self._ws_server = None

    def _make_handler(self):
        ws_url = f"ws://127.0.0.1:{self.ws_port}/devtools/browser/fake"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/json/version":
                    body = json.dumps({"webSocketDebuggerUrl": ws_url}).encode()
                elif self.path == "/json/list":
                    body = b"[]"  # 空列表 -> 触发 Target.createTarget 分支
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: N802
                pass

        return Handler

    async def __aenter__(self):
        handler = self._make_handler()
        self._http = ThreadingHTTPServer(("127.0.0.1", self.http_port), handler)
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

        async def ws_handler(ws):
            async for raw in ws:
                msg = json.loads(raw)
                method = msg.get("method", "")
                resp = {"id": msg.get("id"), "result": {}}
                if method == "Target.createTarget":
                    resp["result"] = {"targetId": "t1"}
                elif method == "Target.attachToTarget":
                    resp["result"] = {"sessionId": "s1"}
                elif method == "Network.enable":
                    await ws.send(json.dumps(resp))
                    # 模拟浏览器：先发 login 请求帧，再收到 login 响应帧
                    sent = {
                        "method": "Network.webSocketFrameSent",
                        "params": {
                            "requestId": "req-1",
                            "response": {"payloadData": _login_request_b64(7)},
                        },
                        "sessionId": "s1",
                    }
                    recv = {
                        "method": "Network.webSocketFrameReceived",
                        "params": {"requestId": "req-1", "response": {"payloadData": self.frame}},
                        "sessionId": "s1",
                    }
                    await ws.send(json.dumps(sent))
                    await ws.send(json.dumps(recv))
                    continue
                await ws.send(json.dumps(resp))

        self._ws_server = await websockets.serve(ws_handler, "127.0.0.1", self.ws_port)
        return self

    async def __aexit__(self, *exc):
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._http:
            threading.Thread(target=self._http.shutdown, daemon=True).start()
            self._http.server_close()


class TestImportTokenE2E(unittest.TestCase):
    """真实 HTTP+WS 模拟 CDP，跑通 import_token 全流程。"""

    def test_full_flow(self):
        http_port, ws_port = _free_port(), _free_port()
        frame = make_login_frame("e2e-captured-token")
        server = FakeCDPServer(http_port, ws_port, frame)

        async def scenario():
            async with server:
                return await token_helper.import_token(port=http_port, timeout=10)

        result = asyncio.run(scenario())
        self.assertEqual(result["access_token"], "e2e-captured-token")
        self.assertEqual(result["credentials"]["method"], ".lq.Lobby.login")

    def test_non_login_response_not_captured(self):
        """无关响应帧（如打牌事件）不应被当作 token 捕获。"""
        http_port, ws_port = _free_port(), _free_port()
        server = FakeCDPServer(http_port, ws_port, frame_b64=make_discard_frame())

        async def scenario():
            async with server:
                with self.assertRaises(TokenImportError):
                    await token_helper.import_token(port=http_port, timeout=0.8)

        asyncio.run(scenario())

    def test_timeout_no_frame(self):
        http_port, ws_port = _free_port(), _free_port()
        server = FakeCDPServer(http_port, ws_port, frame_b64="")

        async def scenario():
            async with server:
                with self.assertRaises(TokenImportError):
                    await token_helper.import_token(port=http_port, timeout=0.5)

        asyncio.run(scenario())


class TestCaptureGameRecord(unittest.TestCase):
    def test_success(self):
        cdp = FakeCDP(9222, mode="record")
        cdp.frame = make_game_record_frame(b"\x08\x01")

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            data = asyncio.run(token_helper.capture_game_record(
                "https://game.maj-soul.com/1/?paipu=test", timeout=10
            ))
        self.assertEqual(data, b"\x08\x01")

    def test_business_error_raises(self):
        # ResGameRecord 带 error（如 1004）
        res = pb.ResGameRecord()
        res.error.code = 1004
        w = pb.Wrapper()
        w.name = ".lq.ResGameRecord"
        w.data = res.SerializeToString()
        raw = b"\x03" + (7).to_bytes(2, "little") + w.SerializeToString()
        frame = base64.b64encode(raw).decode()

        cdp = FakeCDP(9222, mode="record")
        cdp.frame = frame

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            with self.assertRaises(token_helper.CaptureRecordError):
                asyncio.run(token_helper.capture_game_record(
                    "https://game.maj-soul.com/1/?paipu=test", timeout=10
                ))

    def test_timeout_raises(self):
        cdp = FakeCDP(9222, mode="record")
        # 不喂帧 -> 超时

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            with self.assertRaises(token_helper.CaptureRecordError):
                asyncio.run(token_helper.capture_game_record(
                    "https://game.maj-soul.com/1/?paipu=test", timeout=0.3
                ))


class TestCloseBrowser(unittest.TestCase):
    def test_close_sends_browser_close(self):
        cdp = FakeCDP(9222, mode="login")

        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=True), \
             mock.patch.object(token_helper, "CDPClient", return_value=cdp):
            result = asyncio.run(token_helper.close_browser(port=9222))
        self.assertTrue(result)
        # 应发送过 Browser.close
        self.assertTrue(any("Browser.close" in s for s in cdp._ws.messages))

    def test_close_when_not_running_is_noop(self):
        with mock.patch.object(token_helper, "wait_cdp_ready", return_value=False):
            result = asyncio.run(token_helper.close_browser(port=9222))
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
