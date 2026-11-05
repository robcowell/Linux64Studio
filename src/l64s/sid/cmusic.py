"""Music in C projects: the ca65 glue that puts a tune at its address and lets C play it.

A tune (a GoatTracker song packed by gt2reloc, or the data from a .sid) has to sit at the address
it was made for. In a C project that's a fixed area (project.ldcfg), and ``glue`` writes:

* ``music.s``: the tune's data in the area's segment (``.incbin``), and C-callable wrappers round
  the player's entry points, plus a raster interrupt that plays it once a frame;
* ``music.h``: their prototypes.

From C::

    #include "music.h"
    music_init(0);          /* tune 0 */
    music_start();          /* plays once a frame from now on */
    music_sfx(gun, 3);      /* a sound effect on voice 3 (songs packed with sound effect support) */

The interrupt is a raster interrupt at line 0 (in the border, out of a game's way), chained to the
KERNAL's handler so the keyboard and clock carry on. It replaces the CIA timer interrupt, so the
KERNAL's work happens once a frame (50 times a second on PAL) instead of 60.
"""
from __future__ import annotations

from dataclasses import dataclass

MARK = "made by Linux64Studio"        # in the files it writes, so it knows it may write them again


@dataclass
class Tune:
    title: str             # for the comments
    data_file: str         # what music.s .incbin's (relative to music.s)
    load: int              # where the data goes
    size: int
    init: int
    play: int = 0          # 0: the tune plays itself (an RSID's own interrupt): no music_play/start
    skip: int = 0          # bytes to skip at the start of the data file (a .sid's header, a .prg's address)
    sfx: int = 0           # GoatTracker's sound effect entry (0: none)
    volume: int = 0        # GoatTracker's volume entry (0: none)
    area: str = "MUSIC"    # the fixed area (and segment) it goes in


def area_size(size: int) -> int:
    """A fixed area for the tune: its size rounded up to whole pages (room to grow a little)."""
    return max(0x100, (size + 0xFF) & ~0xFF)


def glue(t: Tune, name: str = "music") -> dict[str, str]:
    """{"music.s": ..., "music.h": ...} for the tune (``name`` prefixes the files and functions)."""
    h = lambda v: f"${v:04X}"     # noqa: E731
    skip = f", {t.skip}" if t.skip else ""
    exports = [f"_{name}_init"]
    if t.play:
        exports += [f"_{name}_play", f"_{name}_start", f"_{name}_stop"]
    if t.sfx:
        exports.append(f"_{name}_sfx")
    if t.volume:
        exports.append(f"_{name}_volume")
    s = [f"; {name}.s: {t.title}, {MARK}.",
         f"; The data goes at {h(t.load)}-{h(t.load + t.size - 1)}, in the fixed area {t.area}",
         "; (Project > Properties > Build > Memory layout). Its functions are in "
         f"{name}.h.", "",
         f'        .segment "{t.area}"',
         f'        .incbin "{t.data_file}"{skip}', "",
         f"        .export {', '.join(exports)}"]
    if t.sfx:
        s.append("        .import popax")
    s += ["", '        .segment "CODE"', "",
          f"; void __fastcall__ {name}_init(unsigned char tune): A = the tune, from 0",
          f"_{name}_init:",
          f"        jmp {h(t.init)}"]
    if t.play:
        s += ["",
              f"; void {name}_play(void): once a frame (if you don't use {name}_start)",
              f"_{name}_play:",
              f"        jmp {h(t.play)}",
              "",
              f"; void {name}_start(void): play it once a frame, from a raster interrupt at line 0",
              f"_{name}_start:",
              "        lda playing             ; (already playing: nothing to do)",
              "        bne @done",
              "        sei",
              "        lda $0314               ; the handler it chains to: normally the KERNAL's",
              "        sta chain",
              "        lda $0315",
              "        sta chain+1",
              "        lda #<irq",
              "        sta $0314",
              "        lda #>irq",
              "        sta $0315",
              "        lda #$7F                ; the CIA timer's interrupt off: the raster's replaces it",
              "        sta $DC0D",
              "        lda $DC0D",
              "        lda $D011               ; line 0 (bit 8 of the line clear)",
              "        and #$7F",
              "        sta $D011",
              "        lda #0",
              "        sta $D012",
              "        lda #$01                ; raster interrupt on",
              "        sta $D01A",
              "        sta $D019",
              "        sta playing",
              "        cli",
              "@done:  rts",
              "",
              f"; void {name}_stop(void): back to the KERNAL's interrupt, and silence",
              f"_{name}_stop:",
              "        sei",
              "        lda #0",
              "        sta $D01A",
              "        lda #$01",
              "        sta $D019",
              "        lda playing             ; (only if it was started)",
              "        beq @off",
              "        lda chain",
              "        sta $0314",
              "        lda chain+1",
              "        sta $0315",
              "        lda #0",
              "        sta playing",
              "        lda #$81                ; the CIA timer's interrupt back on",
              "        sta $DC0D",
              "@off:   lda #0",
              "        sta $D418               ; volume 0",
              "        cli",
              "        rts",
              "",
              "irq:    lda $D019               ; ours: the raster's (else the KERNAL's)",
              "        and #$01",
              "        beq @other",
              "        sta $D019               ; acknowledge it",
              f"        jsr {h(t.play)}",
              "@other: jmp $EA31               ; on to the handler it replaced (set by music_start)",
              "chain = @other + 1"]
    if t.sfx:
        s += ["",
              f"; void __fastcall__ {name}_sfx(const unsigned char *effect, unsigned char voice): voice 1-3",
              f"_{name}_sfx:",
              "        tay",
              "        lda channels-1,y        ; voice 1, 2, 3 -> channel 0, 7, 14",
              "        sta channel",
              "        jsr popax               ; the effect: A low, X high",
              "        pha",
              "        txa",
              "        tay                     ; the player takes it in A (low) and Y (high)",
              "        pla",
              "        ldx channel",
              "        php                     ; (no interrupt while the player takes it: it may be playing)",
              "        sei",
              f"        jsr {h(t.sfx)}",
              "        plp",
              "        rts",
              "channels: .byte 0, 7, 14"]
    if t.volume:
        s += ["",
              f"; void __fastcall__ {name}_volume(unsigned char volume): 0-15",
              f"_{name}_volume:",
              "        php",
              "        sei",
              f"        jsr {h(t.volume)}",
              "        plp",
              "        rts"]
    if t.play or t.sfx:
        s += ["", '        .segment "BSS"']
        if t.play:
            s.append("playing: .res 1")
        if t.sfx:
            s.append("channel: .res 1")
    guard = name.upper() + "_H"
    hdr = [f"/* {name}.h: {t.title}, {MARK}. The data is at {h(t.load)}; the code in {name}.s. */",
           f"#ifndef {guard}", f"#define {guard}", "",
           f"void __fastcall__ {name}_init(unsigned char tune);    /* once, first: the tune, from 0 */"]
    if t.play:
        hdr += [f"void {name}_start(void);    /* play it once a frame, from a raster interrupt */",
                f"void {name}_stop(void);     /* stop playing, and silence the SID */",
                f"void {name}_play(void);     /* or call this once a frame yourself, instead of {name}_start */"]
    else:
        hdr.append(f"/* (this tune plays itself once {name}_init has started it) */")
    if t.sfx:
        hdr.append(f"void __fastcall__ {name}_sfx(const unsigned char *effect, unsigned char voice);"
                   "    /* voice 1-3 */")
    if t.volume:
        hdr.append(f"void __fastcall__ {name}_volume(unsigned char volume);    /* 0-15 */")
    hdr += ["", "#endif"]
    return {f"{name}.s": "\n".join(s) + "\n", f"{name}.h": "\n".join(hdr) + "\n"}


def usage(t: Tune, name: str = "music") -> str:
    """The C to play it, for the music pages' code box."""
    out = [f'#include "{name}.h"', "",
           "/* Once, at start-up: */", f"    {name}_init(0);    /* the tune, from 0 */"]
    if t.play:
        out += [f"    {name}_start();    /* plays once a frame from now on (or call {name}_play() each frame) */"]
    if t.sfx:
        out += ["", "/* A sound effect (a GoatTracker instrument converted for the project): */",
                "extern const unsigned char effect[];",
                f"    {name}_sfx(effect, 3);    /* on voice 3 */"]
    if t.volume:
        out += ["", f"    {name}_volume(15);    /* 0-15 */"]
    return "\n".join(out) + "\n"


class InstallError(Exception):
    pass


def install(project, tune: Tune, name: str = "music") -> list[str]:
    """Put the tune into a C project: its fixed area (unless the project links with a config of its
    own: then the lines to add are in the message), music.s and music.h, and music.s on the build
    list. What was done (what changed), a line each: doing it again changes only what's different."""
    from ..project import ldcfg
    from ..project.fileops import build_add
    done = []
    size = area_size(tune.size)
    if project.linker_config:
        done.append(f"Your linker config ({project.linker_config}) needs an area for it: in MEMORY "
                    f"'{tune.area}: file = %O, start = ${tune.load:04X}, size = ${size:04X};' and in SEGMENTS "
                    f"'{tune.area}: load = {tune.area}, type = rw;'")
    else:
        areas = [a for a in project.c_areas if a.get("name", "").upper() != tune.area.upper()]
        new = ldcfg.Area(tune.area, tune.load, size)
        try:
            ldcfg.layout([ldcfg.Area.from_dict(a) for a in areas] + [new])
        except ldcfg.LayoutError as e:
            raise InstallError(f"The music can't go at ${tune.load:04X}: {e}") from None
        now = sorted(areas + [new.to_dict()], key=lambda a: a["start"])
        if now != project.c_areas:
            project.c_areas = now
            done.append(f"Fixed area {tune.area}: ${tune.load:04X}-${tune.load + size - 1:04X}")
    files = glue(tune, name)
    for fname, text in files.items():
        path = project.directory / fname
        if path.exists() and MARK not in path.read_text(errors="replace"):
            raise InstallError(f"{fname} is already in the project, and Linux64Studio didn't write it: rename it, "
                               "or remove it, first")
    for fname, text in files.items():
        path = project.directory / fname
        if not path.exists() or path.read_text(errors="replace") != text:
            path.write_text(text)
            done.append(f"Wrote {fname}")
    if build_add(project, project.directory / f"{name}.s"):
        done.append(f"Added {name}.s to the build list")
    return done
