"""majsoul_ws 单元测试（阶段二）。

不访问网络：mock WebSocket 与 HTTP，验证帧协议、错误码映射、登录/拉取逻辑。
"""

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

import protocol_pb2 as pb  # noqa: E402
import majsoul_ws  # noqa: E402
from majsoul_ws import (  # noqa: E402
    ERR_AUTH,
    ERR_NOT_LOGGED_IN,
    MajsoulAuthError,
    MajsoulError,
    MajsoulNotLoggedInError,
    MajsoulRPCChannel,
)


def _wrap(name: str, data: bytes) -> bytes:
    w = pb.Wrapper()
    w.name = name
    w.data = data
    return w.SerializeToString()


def _error_wrapper(code: int) -> bytes:
    """构造服务端错误响应体：Wrapper{name='', data=ResCommon{error}}。"""
    rc = pb.ResCommon()
    rc.error.code = code
    return _wrap("", rc.SerializeToString())


class FakeWS:
    """可编程 mock WebSocket：预置待收消息队列。"""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


def make_channel(messages):
    """构造已挂接 FakeWS 的通道（dispatcher 由调用方启动）。"""
    ch = MajsoulRPCChannel("wss://fake/gateway")
    ch._ws = FakeWS(messages)
    return ch


async def with_dispatcher(ch, coro):
    """在 dispatcher 运行中执行协程。"""
    task = asyncio.create_task(ch._dispatch())
    try:
        return await coro
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def run(coro):
    return asyncio.run(coro)


class TestFrameCodec(unittest.TestCase):
    def test_wrap_unwrap_roundtrip(self):
        blob = MajsoulRPCChannel.wrap(".lq.Lobby.fetchGameRecord", b"\x08\x01")
        w = MajsoulRPCChannel.unwrap(blob)
        self.assertEqual(w.name, ".lq.Lobby.fetchGameRecord")
        self.assertEqual(w.data, b"\x08\x01")


class TestSendRequest(unittest.TestCase):
    def test_success_response(self):
        req_name = ".lq.Lobby.fetchGameRecord"
        ch = make_channel([])
        idx = ch._next_idx
        frame = bytes([3]) + idx.to_bytes(2, "little") + _wrap(req_name, b"\x08\x07")

        async def scenario():
            ch._ws._messages.append(frame)
            return await ch.send_request(req_name, b"\x08\x01")

        data = run(with_dispatcher(ch, scenario()))
        self.assertEqual(data, b"\x08\x07")
        sent = ch._ws.sent[0]
        self.assertEqual(sent[0], 2)  # REQUEST
        self.assertEqual(sent[1:3], idx.to_bytes(2, "little"))
        w = MajsoulRPCChannel.unwrap(sent[3:])
        self.assertEqual(w.name, req_name)

    def test_error_151_maps_to_auth_error(self):
        ch = make_channel([])
        idx = ch._next_idx
        frame = bytes([3]) + idx.to_bytes(2, "little") + _error_wrapper(ERR_AUTH)

        async def scenario():
            ch._ws._messages.append(frame)
            with self.assertRaises(MajsoulAuthError):
                await ch.send_request(".lq.Lobby.login", b"")

        run(with_dispatcher(ch, scenario()))

    def test_error_1004_maps_to_not_logged_in(self):
        ch = make_channel([])
        idx = ch._next_idx
        frame = bytes([3]) + idx.to_bytes(2, "little") + _error_wrapper(ERR_NOT_LOGGED_IN)

        async def scenario():
            ch._ws._messages.append(frame)
            with self.assertRaises(MajsoulNotLoggedInError):
                await ch.send_request(".lq.Lobby.fetchGameRecord", b"")

        run(with_dispatcher(ch, scenario()))

    def test_unknown_error_code(self):
        ch = make_channel([])
        idx = ch._next_idx
        frame = bytes([3]) + idx.to_bytes(2, "little") + _error_wrapper(999)

        async def scenario():
            ch._ws._messages.append(frame)
            with self.assertRaises(MajsoulError) as ctx:
                await ch.send_request(".lq.Lobby.foo", b"")
            self.assertEqual(ctx.exception.code, 999)

        run(with_dispatcher(ch, scenario()))

    def test_timeout_raises(self):
        ch = make_channel([])  # 无响应

        async def scenario():
            with self.assertRaises(asyncio.TimeoutError):
                await ch.send_request(".lq.Lobby.foo", b"", timeout=0.1)

        run(with_dispatcher(ch, scenario()))

    def test_notify_ignored(self):
        ch = make_channel([])
        idx = ch._next_idx
        notify = bytes([1]) + _wrap(".lq.NotifySomething", b"\x08\x01")
        frame = bytes([3]) + idx.to_bytes(2, "little") + _wrap(".lq.Lobby.foo", b"\x08\x02")

        async def scenario():
            ch._ws._messages.extend([notify, frame])
            return await ch.send_request(".lq.Lobby.foo", b"")

        data = run(with_dispatcher(ch, scenario()))
        self.assertEqual(data, b"\x08\x02")


class TestErrorMapping(unittest.TestCase):
    def test_error_from_code(self):
        self.assertIsInstance(majsoul_ws._error_from_code(151), MajsoulAuthError)
        self.assertIsInstance(majsoul_ws._error_from_code(1004), MajsoulNotLoggedInError)
        err = majsoul_ws._error_from_code(42)
        self.assertIsInstance(err, MajsoulError)
        self.assertEqual(err.code, 42)


if __name__ == "__main__":
    unittest.main()
