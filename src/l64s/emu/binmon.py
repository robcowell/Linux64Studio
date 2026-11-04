"""Client for VICE's binary monitor protocol (VICE 3.5+, API version 2).

Start VICE with `-binarymonitor -binarymonitoraddress ip4://127.0.0.1:<port>`.
Requests and responses are framed as documented in the VICE manual, "Binary Monitor".
A background thread reads responses; events (stopped, resumed, checkpoint hit) go to
`on_event(type, body)`, called from that thread, so GUI callers should hop to their main loop.
"""
from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass

API_VERSION = 0x02
STX = 0x02
EVENT_ID = 0xFFFFFFFF

CMD_MEM_GET = 0x01
CMD_MEM_SET = 0x02
CMD_CHECKPOINT_GET = 0x11
CMD_CHECKPOINT_SET = 0x12
CMD_CHECKPOINT_DELETE = 0x13
CMD_CHECKPOINT_LIST = 0x14
CMD_CHECKPOINT_TOGGLE = 0x15
CMD_REGISTERS_GET = 0x31
CMD_REGISTERS_SET = 0x32
CMD_ADVANCE = 0x71
CMD_EXECUTE_UNTIL_RETURN = 0x73
CMD_PING = 0x81
CMD_REGISTERS_AVAILABLE = 0x83
CMD_EXIT = 0xAA
CMD_QUIT = 0xBB
CMD_RESET = 0xCC
CMD_AUTOSTART = 0xDD

EVT_CHECKPOINT = 0x11
EVT_JAM = 0x61
EVT_STOPPED = 0x62
EVT_RESUMED = 0x63

OP_LOAD, OP_STORE, OP_EXEC = 1, 2, 4


class MonitorError(Exception):
    pass


@dataclass
class Checkpoint:
    id: int
    hit: bool
    start: int
    end: int
    stop: bool
    enabled: bool
    op: int
    temporary: bool
    hit_count: int


def parse_checkpoint(body: bytes) -> Checkpoint:
    cid, hit, start, end, stop, enabled, op, temp, hits = struct.unpack_from("<IBHHBBBBI", body)
    return Checkpoint(cid, bool(hit), start, end, bool(stop), bool(enabled), op, bool(temp), hits)


class _Pending:
    def __init__(self):
        self.event = threading.Event()
        self.responses: list[tuple[int, int, bytes]] = []


class BinaryMonitor:
    def __init__(self, on_event=None):
        self.sock: socket.socket | None = None
        self.on_event = on_event
        self._next_id = 1
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._reader: threading.Thread | None = None
        self.reg_names: dict[int, str] = {}
        self.connected = False

    # -------------------------------------------------------------- connection
    def connect(self, host: str = "127.0.0.1", port: int = 6502, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(None)
        self.connected = True
        self._reader = threading.Thread(target=self._read_loop, name="vice-binmon", daemon=True)
        self._reader.start()
        try:
            self.reg_names = self.registers_available()
        except MonitorError:
            self.reg_names = {}

    def close(self) -> None:
        self.connected = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("VICE closed the monitor connection")
            buf += chunk
        return bytes(buf)

    def _read_loop(self) -> None:
        try:
            while self.connected:
                header = self._recv_exact(12)
                stx, api, length, rtype, err, rid = struct.unpack("<BBIBBI", header)
                if stx != STX:
                    raise ConnectionError("Bad response from VICE")
                body = self._recv_exact(length)
                if rid == EVENT_ID:
                    if self.on_event:
                        self.on_event(rtype, body)
                    continue
                with self._lock:
                    p = self._pending.get(rid)
                if p:
                    p.responses.append((rtype, err, body))
                    p.event.set()
                elif self.on_event:
                    # e.g. checkpoint hit responses tagged with the id of an earlier request
                    self.on_event(rtype, body)
        except (OSError, ConnectionError):
            pass
        finally:
            self.connected = False
            if self.on_event:
                self.on_event(-1, b"")

    def request(self, cmd: int, body: bytes = b"", timeout: float = 5.0) -> tuple[int, bytes]:
        if not self.sock or not self.connected:
            raise MonitorError("Not connected to VICE")
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            p = _Pending()
            self._pending[rid] = p
        frame = struct.pack("<BBIIB", STX, API_VERSION, len(body), rid, cmd) + body
        try:
            self.sock.sendall(frame)
            if not p.event.wait(timeout):
                raise MonitorError(f"VICE didn't answer command ${cmd:02X}")
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        rtype, err, rbody = p.responses[-1]
        if err:
            raise MonitorError(f"VICE monitor error ${err:02X} for command ${cmd:02X}")
        return rtype, rbody

    # -------------------------------------------------------------- commands
    def ping(self) -> None:
        self.request(CMD_PING)

    def resume(self) -> None:
        self.request(CMD_EXIT)

    def quit(self) -> None:
        try:
            self.request(CMD_QUIT, timeout=1.0)
        except MonitorError:
            pass

    def reset(self, hard: bool = False) -> None:
        self.request(CMD_RESET, bytes([1 if hard else 0]))

    def read_memory(self, start: int, end: int, side_effects: bool = False) -> bytes:
        body = struct.pack("<BHHBH", int(side_effects), start, end, 0, 0)
        _, r = self.request(CMD_MEM_GET, body)
        n = struct.unpack_from("<H", r)[0]
        return r[2:2 + n] if n else r[2:]

    def write_memory(self, start: int, data: bytes) -> None:
        body = struct.pack("<BHHBH", 0, start, start + len(data) - 1, 0, 0) + data
        self.request(CMD_MEM_SET, body)

    def registers_available(self) -> dict[int, str]:
        _, r = self.request(CMD_REGISTERS_AVAILABLE, b"\x00")
        count = struct.unpack_from("<H", r)[0]
        off, names = 2, {}
        for _ in range(count):
            size = r[off]
            rid, _bits, nlen = r[off + 1], r[off + 2], r[off + 3]
            names[rid] = r[off + 4:off + 4 + nlen].decode("ascii", "replace")
            off += size + 1
        return names

    def get_registers(self) -> dict[str, int]:
        _, r = self.request(CMD_REGISTERS_GET, b"\x00")
        count = struct.unpack_from("<H", r)[0]
        off, regs = 2, {}
        for _ in range(count):
            size = r[off]
            rid, value = struct.unpack_from("<BH", r, off + 1)
            regs[self.reg_names.get(rid, f"R{rid}")] = value
            off += size + 1
        return regs

    def set_register(self, name: str, value: int) -> None:
        ids = {v: k for k, v in self.reg_names.items()}
        if name not in ids:
            raise MonitorError(f"Unknown register {name}")
        body = struct.pack("<BH", 0, 1) + struct.pack("<BBH", 3, ids[name], value & 0xFFFF)
        self.request(CMD_REGISTERS_SET, body)

    def add_checkpoint(self, start: int, end: int | None = None, op: int = OP_EXEC,
                       stop: bool = True, temporary: bool = False) -> Checkpoint:
        body = struct.pack("<HHBBBB", start, end if end is not None else start, int(stop), 1, op, int(temporary))
        _, r = self.request(CMD_CHECKPOINT_SET, body)
        return parse_checkpoint(r)

    def delete_checkpoint(self, cid: int) -> None:
        self.request(CMD_CHECKPOINT_DELETE, struct.pack("<I", cid))

    def step(self, count: int = 1, over: bool = False) -> None:
        self.request(CMD_ADVANCE, struct.pack("<BH", int(over), count))

    def step_out(self) -> None:
        self.request(CMD_EXECUTE_UNTIL_RETURN)

    def autostart(self, path: str, run: bool = True) -> None:
        name = path.encode()
        self.request(CMD_AUTOSTART, struct.pack("<BHB", int(run), 0, len(name)) + name, timeout=15)
