"""The simulated C64's disk drive (emu.sim): a 1541 on the serial bus, at the level of the KERNAL's
bus routines, as Rift64's emulated drives and VICE's virtual devices do it.

The simulator takes the KERNAL's serial routines over at their entry points (LISTEN, TALK, SECOND,
TKSA, CIOUT, ACPTR, UNLSN, UNTLK: ``Bus``), so everything above them is the real KERNAL: LOAD, SAVE,
OPEN, CHKIN, GET#, PRINT#, CLOSE, the status in ST ($90) and its errors. What the drive does with
the commands and bytes is this module's ``Drive``, the 1541's DOS over a disk image (disk.image):

* files: LOAD and SAVE; OPEN to read, write (``,S,W``, ``,P,W``, ``,U,W``) or append (``,A``) a PRG,
  SEQ or USR file; ``@0:`` to replace one; ``*`` and ``?`` in names; ``$`` for the directory (with a
  pattern, ``$0:A*``, and a type, ``$:*=P``), as a BASIC program as a 1541 sends it;
* the command channel (15): its error message (``73,CBM DOS V2.6 1541,00,00`` at first, then
  ``00, OK,00,00`` or the error), and the DOS commands I, UI, S (scratch), R (rename), C (copy),
  V (validate), N (new);
* buffers (``#``) and the block commands U1, U2, B-R, B-W, B-A, B-F, B-P (B-E, M-W and M-E are taken
  and do nothing: the drive has no 6502 to run code; M-R reads zeros).

Not there: relative (REL) files, a drive's speed (it loads as fast as VICE's virtual devices do),
fast loaders and anything else that drives the bus lines itself, and the 1541's limit of open files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..disk.image import CLOSED, LOCKED, PAD, DiskError, DiskImage, from_petscii_name

CR = 0x0D
ST_EOI, ST_TIMEOUT, ST_NOT_PRESENT = 0x40, 0x02, 0x80
ERRORS = {0: " OK", 1: " FILES SCRATCHED", 20: "READ ERROR", 30: "SYNTAX ERROR", 31: "SYNTAX ERROR",
          32: "SYNTAX ERROR", 33: "SYNTAX ERROR", 34: "SYNTAX ERROR", 60: "WRITE FILE OPEN",
          61: "FILE NOT OPEN", 62: "FILE NOT FOUND", 63: "FILE EXISTS", 64: "FILE TYPE MISMATCH",
          65: "NO BLOCK", 66: "ILLEGAL TRACK OR SECTOR", 70: "NO CHANNEL", 72: "DISK FULL",
          73: "CBM DOS V2.6 1541", 74: "DRIVE NOT READY"}
TYPE_LETTERS = {ord("P"): "prg", ord("S"): "seq", ord("U"): "usr", ord("L"): "rel"}


def matches(pattern: bytes, name: bytes) -> bool:
    """Whether a file name fits a DOS pattern: ``?`` any one character, ``*`` the rest of the name."""
    for i, c in enumerate(pattern):
        if c == 0x2A:                                    # *
            return True
        if i >= len(name) or (c != 0x3F and c != name[i]):
            return False
    return len(pattern) == len(name)


@dataclass
class _Channel:
    kind: str                       # "read" (a file or the directory), "write", "buffer"
    data: bytearray = field(default_factory=bytearray)
    pos: int = 0
    name: bytes = b""               # a file being written: its name, type, and whether it replaces one
    file_type: str = "seq"
    replace: bool = False
    length: int = 256               # a buffer: where reading it ends (256, or as B-R says)


@dataclass
class _Open:
    """A file name, as an OPEN gives it: ``@0:NAME,S,W``."""
    name: bytes
    replace: bool = False
    file_type: str | None = None
    mode: int | None = None         # ord("R"), "W", "A", "M"
    directory: bool = False


def parse_name(raw: bytes) -> _Open:
    raw = raw.split(bytes([CR]))[0]
    if raw.startswith(b"$"):
        return _Open(raw[1:], directory=True)
    replace = raw.startswith(b"@")
    if replace:
        raw = raw[1:]
    m = re.match(rb"[0-9]?:", raw)
    if m:
        raw = raw[m.end():]
    name, *options = raw.split(b",")
    out = _Open(name, replace)
    for option in options:
        letter = option.strip()[:1]
        if letter and letter[0] in TYPE_LETTERS:
            out.file_type = TYPE_LETTERS[letter[0]]
        elif letter and letter in b"RWAM":
            out.mode = letter[0]
    return out


class Drive:
    """A 1541's DOS, on the bus: ``listen``/``talk``, ``second`` (the secondary address as sent: $60
    data, $E0 close, $F0 open, with the channel), ``send`` a byte to it, ``receive`` one from it, and
    ``unlisten``/``untalk``. ``image``: the disk in it (a ``DiskImage``), or None for none."""

    def __init__(self, image: DiskImage | None = None):
        self.image = image
        self.changed = False                     # the disk has been written to
        self.reset()

    def reset(self) -> None:
        """As at power-on: no channels open, and the DOS's message."""
        self.channels: dict[int, _Channel] = {}
        self.listening = self.talking = False
        self.channel: int | None = None          # the channel the secondary address chose
        self.command: int | None = None          # $60, $E0 or $F0
        self.incoming = bytearray()              # a name, or a command, as it comes
        self._set_error(73)

    # -------------------------------------------------------------- the error channel
    def _set_error(self, code: int, track: int = 0, sector: int = 0, text: str | None = None) -> None:
        text = ERRORS.get(code, "") if text is None else text
        self.error = (code, track, sector)
        self.message = bytearray(f"{code:02d},{text},{track:02d},{sector:02d}".encode("ascii") + bytes([CR]))
        self.message_pos = 0

    @property
    def status(self) -> str:
        """The error channel's message, as text."""
        return self.message.rstrip(bytes([CR])).decode("ascii", "replace")

    # -------------------------------------------------------------- the bus
    def listen(self) -> None:
        self.listening, self.talking = True, False
        self.channel = self.command = None
        self.incoming.clear()

    def talk(self) -> None:
        self.talking, self.listening = True, False
        self.channel = self.command = None

    def second(self, sa: int) -> None:
        self.channel, self.command = sa & 0x0F, sa & 0xF0
        self.incoming.clear()
        if self.listening and self.command == 0xE0:
            self.close(self.channel)

    def send(self, byte: int) -> None:
        if not self.listening or self.channel is None:
            return
        ch = self.channels.get(self.channel)
        if self.command == 0xF0 or self.channel == 15:
            self.incoming.append(byte)
        elif ch is not None and ch.kind == "write":
            ch.data.append(byte)
        elif ch is not None and ch.kind == "buffer":
            ch.data[ch.pos] = byte
            ch.pos = (ch.pos + 1) & 0xFF

    def unlisten(self) -> None:
        if self.listening and self.channel is not None:
            if self.channel == 15 and self.incoming:
                self.run_command(bytes(self.incoming))
            elif self.command == 0xF0:
                self.open(self.channel, bytes(self.incoming))
        self.listening = False
        self.channel = self.command = None
        self.incoming.clear()

    def untalk(self) -> None:
        self.talking = False
        self.channel = self.command = None

    def receive(self) -> tuple[int, int]:
        """The next byte from the channel talking, and the ST bits that come with it: EOI ($40) with
        the last; a timeout as well ($42) when there's nothing to send."""
        if not self.talking or self.channel is None:
            return CR, ST_EOI | ST_TIMEOUT
        if self.channel == 15:
            b = self.message[self.message_pos]
            self.message_pos += 1
            if self.message_pos >= len(self.message):
                self._set_error(0)                       # (read, the error's gone)
                return b, ST_EOI
            return b, 0
        ch = self.channels.get(self.channel)
        if ch is None or ch.kind == "write":
            return CR, ST_EOI | ST_TIMEOUT
        if ch.kind == "buffer":
            b = ch.data[ch.pos]
            end = ch.pos + 1 >= ch.length
            ch.pos = 1 if end else ch.pos + 1
            return b, ST_EOI if end else 0
        if ch.pos >= len(ch.data):
            return CR, ST_EOI | ST_TIMEOUT
        b = ch.data[ch.pos]
        ch.pos += 1
        return b, ST_EOI if ch.pos >= len(ch.data) else 0

    # -------------------------------------------------------------- files
    def _entries(self, pattern: bytes, file_type: str | None = None):
        for e in self.image.entries():
            if e.file_type != "del" and matches(pattern, e.raw_name) and (file_type is None or e.file_type == file_type):
                yield e

    def open(self, channel: int, raw: bytes) -> None:
        self.channels.pop(channel, None)
        if channel == 15:
            if raw:
                self.run_command(raw)
            return
        o = parse_name(raw)
        if o.name.startswith(b"#"):
            self.channels[channel] = _Channel("buffer", bytearray(256), pos=1)
            self._set_error(0)
            return
        if self.image is None:
            self._set_error(74)
            return
        if o.directory:
            self.channels[channel] = _Channel("read", self.directory(o.name))
            self._set_error(0)
            return
        if not o.name:
            self._set_error(34)
            return
        if o.file_type == "rel":
            self._set_error(64)
            return
        writing = o.mode in (ord("W"), ord("A")) or (o.mode is None and channel == 1)
        if writing:
            self._open_write(channel, o)
            return
        entry = next(self._entries(o.name), None)
        if entry is None:
            self._set_error(62)
            return
        if o.file_type is not None and entry.file_type != o.file_type:
            self._set_error(64)
            return
        self.channels[channel] = _Channel("read", bytearray(self.image.read_file(entry)))
        self._set_error(0)

    def _open_write(self, channel: int, o: _Open) -> None:
        name = o.name[:16]
        if b"*" in name or b"?" in name:
            self._set_error(33)
            return
        existing = self.image.find(name)
        ch = _Channel("write", name=name, file_type=o.file_type or ("prg" if channel == 1 else "seq"))
        if o.mode == ord("A"):
            if existing is None:
                self._set_error(62)
                return
            ch.data = bytearray(self.image.read_file(existing))
            ch.file_type, ch.replace = existing.file_type, True
        elif existing is not None:
            if not o.replace:
                self._set_error(63)
                return
            ch.replace = True
        self.channels[channel] = ch
        self._set_error(0)

    def close(self, channel: int) -> None:
        """Close a channel (a file being written goes onto the disk). Closing 15 closes them all."""
        for n in (list(self.channels) if channel == 15 else [channel]):
            ch = self.channels.pop(n, None)
            if ch is not None and ch.kind == "write":
                self._write(ch)

    def _write(self, ch: _Channel) -> None:
        before = bytes(self.image.data)
        try:
            self.image.add_file(ch.name, bytes(ch.data), ch.file_type, replace=ch.replace)
        except DiskError:
            self.image.data[:] = before
            self._set_error(72)
            return
        self.changed = True
        self._set_error(0)

    def directory(self, spec: bytes) -> bytearray:
        """The directory as a 1541 sends it for ``$`` (``spec``: what follows, ``0:A*=P``): a BASIC
        program at $0401, a line for the disk's name and ID, one per file (its blocks the line
        number) and BLOCKS FREE."""
        m = re.match(rb"[0-9]?:?([^=]*)(?:=(.))?", spec)
        pattern = m.group(1) or b"*"
        file_type = TYPE_LETTERS.get(m.group(2)[0]) if m.group(2) else None
        img, f = self.image, self.image.fmt
        hdr = img.sector(*f.header)
        out = bytearray([0x01, 0x04])

        def line(number: int, text: bytes) -> None:
            out.extend(bytes([0x01, 0x01, number & 0xFF, number >> 8]) + text + b"\0")
        name = bytes(hdr[f.name_offset:f.name_offset + 16])
        disk_id = bytes(hdr[f.id_offset:f.id_offset + 5]).replace(bytes([PAD]), b" ")
        line(0, b'\x12"' + name.replace(bytes([PAD]), b" ") + b'" ' + disk_id)
        for e in self._entries(pattern, file_type):
            digits = len(str(e.blocks))
            text = b" " * max(0, 4 - digits) + b'"' + e.raw_name + b'"'
            text += b" " * (max(0, 4 - digits) + 18 - len(text))
            text += (b" " if e.type_byte & CLOSED else b"*") + e.file_type.upper().encode()
            text += b"<" if e.type_byte & LOCKED else b" "
            line(e.blocks, text.ljust(27 - max(0, digits - 1)))
        line(img.blocks_free, b"BLOCKS FREE.".ljust(25))
        out.extend(b"\0\0")
        return out

    # -------------------------------------------------------------- commands
    def run_command(self, raw: bytes) -> None:
        """A DOS command, as PRINT#15 (or OPEN 15,8,15,"...") sends it."""
        if raw.endswith(bytes([CR])):
            raw = raw[:-1]
        text = bytes(b & 0x7F if b >= 0xC0 else b for b in raw)
        c = text[:1]
        if c == b"I":
            self._set_error(0)
        elif text[:2] in (b"UI", b"U:", b"UJ"):
            self.reset()
        elif re.match(rb"U[1A2B]", text):
            self._user_block(text[2:], text[1:2] in b"2B")
        elif re.match(rb"B[A-Z]*-[RWAFPE]", text):
            self._block(text)
        elif text.startswith(b"M-R"):
            n = raw[5] if len(raw) > 5 else 1
            self.message, self.message_pos = bytearray(n or 256), 0
            self.error = (0, 0, 0)
        elif text.startswith((b"M-W", b"M-E")):
            self._set_error(0)
        elif self.image is None and c in (b"S", b"R", b"C", b"V", b"N"):
            self._set_error(74)
        elif c == b"S":
            self._scratch(raw)
        elif c == b"R":
            self._rename(raw)
        elif c == b"C":
            self._copy(raw)
        elif c == b"V":
            self.image.validate()
            self.changed = True
            self._set_error(0)
        elif c == b"N":
            self._new(raw)
        else:
            self._set_error(31)

    @staticmethod
    def _after_colon(raw: bytes) -> bytes | None:
        i = raw.find(b":")
        return None if i < 0 else raw[i + 1:]

    def _scratch(self, raw: bytes) -> None:
        names = self._after_colon(raw)
        if not names:
            self._set_error(34)
            return
        count = 0
        for pattern in names.split(b","):
            pattern = re.sub(rb"^[0-9]?:", b"", pattern)
            for e in list(self._entries(pattern)):
                if not e.locked:
                    self.image.delete(e)
                    count += 1
        self.changed = self.changed or count > 0
        self._set_error(1, min(count, 99))

    def _two_names(self, raw: bytes) -> tuple[bytes, list[bytes]] | None:
        rest = self._after_colon(raw)
        if rest is None or b"=" not in rest:
            return None
        new, old = rest.split(b"=", 1)
        olds = [re.sub(rb"^[0-9]?:", b"", n) for n in old.split(b",")]
        return (new[:16], olds) if new and all(olds) else None

    def _rename(self, raw: bytes) -> None:
        names = self._two_names(raw)
        if names is None:
            self._set_error(34)
            return
        new, (old, *_) = names
        if any(c in new + old for c in b"*?"):
            self._set_error(33)
        elif self.image.find(new) is not None:
            self._set_error(63)
        elif (e := self.image.find(old)) is None:
            self._set_error(62)
        else:
            t, s, i = e.slot
            self.image.sector(t, s)[i * 32 + 5:i * 32 + 21] = new + bytes([PAD]) * (16 - len(new))
            self.changed = True
            self._set_error(0)

    def _copy(self, raw: bytes) -> None:
        names = self._two_names(raw)
        if names is None:
            self._set_error(34)
            return
        new, olds = names
        if self.image.find(new) is not None:
            self._set_error(63)
            return
        files = [self.image.find(o) for o in olds]
        if None in files:
            self._set_error(62)
            return
        self._write(_Channel("write", bytearray(b"".join(self.image.read_file(e) for e in files)), name=new,
                             file_type=files[0].file_type))

    def _new(self, raw: bytes) -> None:
        rest = self._after_colon(raw)
        if not rest:
            self._set_error(34)
            return
        name, _, disk_id = rest.partition(b",")
        try:
            self.image.format(from_petscii_name(name[:16]), from_petscii_name(disk_id[:2]) if disk_id
                              else self.image.disk_id)
        except DiskError:
            self._set_error(34)
            return
        self.channels.clear()
        self.changed = True
        self._set_error(0)

    # -------------------------------------------------------------- buffers and blocks
    @staticmethod
    def _numbers(text: bytes) -> tuple[list[int], bool]:
        """Up to four decimal numbers, with spaces, commas, ')', '#' and cursor right between, as
        VICE's virtual drive reads them (missing ones are 0); and whether more follows (an error)."""
        numbers, at, found = [0, 0, 0, 0], 0, 0
        while found < 4:
            while at < len(text) and text[at] in b" ),#\x1d":
                at += 1
            if at >= len(text):
                break
            m = re.match(rb"[+-]?\d*", text[at:])
            numbers[found] = int(m.group(0)) if m.group(0).strip(b"+-") else 0
            at += len(m.group(0)) or 1
            found += 1
        return numbers, found == 4 and at < len(text) and bytes([text[at]]).isalnum()

    def _buffer(self, channel: int) -> _Channel | None:
        ch = self.channels.get(channel)
        if ch is None or ch.kind != "buffer":
            self._set_error(70)
            return None
        return ch

    def _sector(self, drive: int, track: int, sector: int):
        if self.image is None or drive != 0:
            return None
        try:
            return self.image.sector(track, sector)
        except DiskError:
            return None

    def _user_block(self, text: bytes, write: bool) -> None:
        (channel, drive, track, sector), extra = self._numbers(text.lstrip(b":"))
        if extra:
            self._set_error(30)
            return
        ch = self._buffer(channel)
        if ch is None:
            return
        sec = self._sector(drive, track, sector)
        if sec is None:
            self._set_error(66, track, sector)
            return
        if write:
            sec[:] = ch.data
            self.changed = True
        else:
            ch.data[:] = sec
            ch.length = 256
        ch.pos = 0
        self._set_error(0)

    def _block(self, text: bytes) -> None:
        m = re.match(rb"B[A-Z]*-([A-Z])[A-Z]*:?", text)
        (a, b, c, d), extra = self._numbers(text[m.end():])
        if extra:
            self._set_error(30)
            return
        op = m.group(1)
        if op == b"E":
            self._set_error(0)
        elif op == b"P":
            if (ch := self._buffer(a)) is not None:
                ch.pos = b & 0xFF
                self._set_error(0)
        elif op in (b"R", b"W"):
            ch = self._buffer(a)
            if ch is None:
                return
            sec = self._sector(b, c, d)
            if sec is None:
                self._set_error(66, c, d)
                return
            if op == b"R":
                ch.data[:] = sec
                ch.length, ch.pos = ch.data[0] + 1, 1
            else:
                ch.data[0] = max(ch.pos - 1, 1)
                sec[:] = ch.data
                ch.pos = 1
                self.changed = True
            self._set_error(0)
        elif op in (b"A", b"F"):
            if self._sector(a, b, c) is None:
                self._set_error(66 if self.image is not None else 74, b, c)
            elif op == b"F":
                self.image._set(b, c, True)
                self.changed = True
                self._set_error(0)
            elif self.image.is_free(b, c):
                self.image._set(b, c, False)
                self.changed = True
                self._set_error(0)
            else:
                self._set_error(65, *self._next_free(b, c))
        else:
            self._set_error(31)

    def _next_free(self, track: int, sector: int) -> tuple[int, int]:
        """The block B-A suggests when the one asked for is taken: the next a file would get."""
        if track == self.image.fmt.dir_track:
            return 0, 0
        try:
            t, s = self.image._allocate_next((track, sector))
        except DiskError:
            return 0, 0
        self.image._set(t, s, True)
        return t, s


# The KERNAL's serial bus routines, by their entry points (the jump table at $FF93-$FFB4 jumps to
# them, and the KERNAL's LOAD, OPEN and the rest call them there).
TALK, LISTEN, SECOND, TKSA, CIOUT, UNTLK, UNLSN, ACPTR = 0xED09, 0xED0C, 0xEDB9, 0xEDC7, 0xEDDD, 0xEDEF, 0xEDFE, 0xEE13
ROUTINES = (TALK, LISTEN, SECOND, TKSA, CIOUT, UNTLK, UNLSN, ACPTR)


class Bus:
    """The serial bus, with ``drives`` on it by device number ({8: Drive()}). ``routine(pc, cpu,
    ram)`` does what the KERNAL's routine at ``pc`` would, with the drive at the other end: the
    registers, flags and ST ($90) as it leaves them. The caller then returns from it."""

    def __init__(self, drives: dict[int, Drive] | None = None):
        self.drives = {8: Drive()} if drives is None else drives
        self.listener: Drive | None = None
        self.talker: Drive | None = None

    def reset(self) -> None:
        self.listener = self.talker = None
        for d in self.drives.values():
            d.reset()

    def routine(self, pc: int, cpu, ram) -> None:
        a = cpu.a
        status = 0
        if pc in (LISTEN, TALK):
            drive = self.drives.get(a & 0x1F)
            if pc == LISTEN:
                self.listener = drive
            else:
                self.talker = drive
            if drive is None:
                status = ST_NOT_PRESENT
            elif pc == LISTEN:
                drive.listen()
            else:
                drive.talk()
        elif pc == SECOND:
            if self.listener is None:
                status = ST_NOT_PRESENT
            else:
                self.listener.second(a)
        elif pc == TKSA:
            if self.talker is None:
                status = ST_NOT_PRESENT
            else:
                self.talker.second(a)
        elif pc == CIOUT:
            if self.listener is None:
                status = ST_NOT_PRESENT
            else:
                self.listener.send(a)
        elif pc == UNLSN:
            if self.listener is not None:
                self.listener.unlisten()
            self.listener = None
        elif pc == UNTLK:
            if self.talker is not None:
                self.talker.untalk()
            self.talker = None
        elif pc == ACPTR:
            byte, status = (CR, ST_EOI | ST_TIMEOUT) if self.talker is None else self.talker.receive()
            cpu.a = byte
            cpu.p = (cpu.p & ~0x82) | (byte & 0x80) | (0x02 if byte == 0 else 0)
        if status:
            ram[0x90] |= status
        if pc in (CIOUT, ACPTR):
            cpu.p &= ~0x01                                # carry clear
        if pc != CIOUT:
            cpu.p &= ~0x04                                # the KERNAL's routines end with CLI
