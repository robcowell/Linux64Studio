"""Playing SID register settings live: an idle VICE vsid (its real reSID emulation, no tune
loaded) that we write $D400-$D418 into through the binary monitor."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from ..emu.binmon import BinaryMonitor, MonitorError
from ..emu.vice import free_port, wait_for_port
from .designer import SID_BASE

MODELS = {"6581": 256, "8580": 257}


class LiveError(RuntimeError):
    pass


def find_vsid(preferred: str = "") -> str | None:
    if preferred and Path(preferred).is_file():
        return preferred
    return shutil.which(preferred or "vsid") or shutil.which("vsid")


class LiveSid:
    def __init__(self, vsid: str = "", model: str = "6581", extra_args: list[str] | None = None):
        self.vsid = vsid
        self.model = model
        self.extra_args = extra_args or []
        self.proc: subprocess.Popen | None = None
        self.mon: BinaryMonitor | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and self.mon is not None

    def start(self, timeout: float = 10.0) -> None:
        """Start vsid (slow: call it off the main thread). Safe to call when already running."""
        with self._lock:
            if self.running:
                return
            self._stop_locked()
            exe = find_vsid(self.vsid)
            if not exe:
                raise LiveError("VICE's vsid isn't installed (it comes with the vice package)")
            port = free_port()
            args = [exe, "-minimized", "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}",
                    "-sidenginemodel", str(MODELS.get(self.model, 256)), *self.extra_args]
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
            if not wait_for_port(port, timeout):
                self._stop_locked()
                raise LiveError("vsid didn't open its monitor port")
            mon = BinaryMonitor()
            try:
                mon.connect(port=port)
            except OSError as e:
                self._stop_locked()
                raise LiveError(f"Couldn't connect to vsid: {e}") from e
            self.mon = mon

    def write(self, registers: bytes, offset: int = 0) -> None:
        """Write registers starting at $D400+offset, and let the emulation run on."""
        with self._lock:
            if not self.running:
                raise LiveError("vsid isn't running")
            try:
                self.mon.write_memory(SID_BASE + offset, bytes(registers), side_effects=True)
                self.mon.resume()
            except (OSError, MonitorError, TimeoutError) as e:
                self._stop_locked()
                raise LiveError(f"Lost the connection to vsid: {e}") from e

    def silence(self) -> None:
        if self.running:
            self.write(bytes(25))

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self.mon:
            try:
                self.mon.quit()
            except Exception:
                pass
            try:
                self.mon.close()
            except Exception:
                pass
            self.mon = None
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None
