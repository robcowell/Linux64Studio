# The CBM prg Studio assembler dialect, as implemented by Linux64Studio

This is what the built-in assembler accepts. Rules marked **verified** were confirmed by
assembling all twelve *Retro Game Dev C64 Edition* Vol 1 chapter projects (chapters 6–17) and
getting output byte-for-byte identical to the `.prg` files shipped with the book
(`tests/test_book.py`). The other rules follow CBM prg Studio's documented behaviour.

## Lines

```
label   mnemonic operand   ; comment
```

* A **label** starts in column 1. A trailing `:` is optional. Any word in column 1 that isn't
  a mnemonic, directive or macro name is a label, so `incbin` and `Operator` can also start
  in column 1. **verified**
* `NAME = expr` defines a constant (`NAME EQU expr` works too). **verified**
* **Labels are case-insensitive** (`PlayerXLow` and `playerXLow` are the same). **verified**
* **Macro names are case-sensitive**, and they don't clash with labels: the book has a macro
  `GAMEBULLETS_COLLIDED` and a label `gameBullets_Collided`. **verified**
* `@name` labels are local. In a macro they're unique to each expansion **(verified)**.
  Outside macros they belong to the most recent ordinary label.
* Comments: `;`, `//` and `/* ... */`.

## Origin

`*=$0801` or `* = $1F20`. You can have several. Gaps are filled with the project's padding
byte (0). **verified**

## Numbers and expressions

| Form | Meaning |
|---|---|
| `$FF`, `%1010`, `@17`, `255` | hex, binary, octal, decimal |
| `'a'` or `` `a` `` | **screen code** of the character (`'a'` = 1, `'@'` = 0, space = 32) **verified** |
| `"a"` | the character's ASCII code |
| `*` | current address |
| `<expr`, `>expr` | low / high byte |
| `+ - * / % << >> & \|` | arithmetic and bitwise, usual precedence |
| `mod and or xor not` | the same as words (`not` gives 1 for 0, otherwise 0), any case |
| `^` | power, grouping to the right (`2^3` = 8). Not XOR: use `xor` |
| `= == <> != < > <= >=` | comparisons (1 or 0), for `if` |
| `#` inside an expression | ignored: the book's `lda #1<<#/1` means `1 << /1` **verified** |

### Base conversion in the editor

As in CBM prg Studio, hover over a number in an assembler file to see it in hex, decimal and
binary. For a byte it also shows the signed value; for a word, its high and low bytes. To
rewrite a number in another base, select it (or just right-click it) and choose **Convert Number
→ Hexadecimal / Decimal / Binary**. A selection may include the `#` of an immediate value.
Hex is written with 2 or 4 digits, binary with 8 or 16, and a wider original (`$0012`) keeps its
width. Numbers inside quotes and digits that are part of a name (`label2`, `/1`) aren't numbers.
Each conversion is one undo step.

### Auto-complete and Go to Definition in the editor

As you type a name, a list under the cursor offers what could finish it: the project's labels,
constants and macros first (this file's, then the others', each with where it's defined), then
instructions and directives. Up/Down choose, Enter or Tab puts it in, Escape closes the list.
Ctrl+Space opens it at any time; **Preferences → Suggest completions as you type** turns the
automatic list off. It isn't offered in comments or strings. In BASIC it offers the keywords.

**F12**, **Ctrl+click** or right-click → **Go to Definition** opens where the name under the
cursor is defined; **Alt+Left** goes back. On an `incasm`, `incbin`, `#import` or `.import` line it
opens that file, and in BASIC it goes to the line a `GOTO`/`GOSUB`/`THEN` names (or a pBASIC
`@label`). When a name is defined in several places (a label local to each of several files), it
asks which, starting with the current file. Hovering over a name shows where it's defined, that
line, and its value in the last build.

Both dialects are understood, from the source as it is (unsaved changes included, no build
needed). CBM prg Studio: labels in column 1, `NAME = value`, `defm`, and `@local` labels (found
under the label they follow); labels are any case. Kick Assembler: `name:`, `.const`, `.var`,
`.label`, `.macro`, `.function`, `.pseudocommand`, `.namespace` and `ns.name`, all
case-sensitive. Every label in the 12 Vol 1 chapters, and every label in Kick Assembler's debug
dump of a Kick Assembler game, is found at the line that defines it (`tests/test_symindex.py`).

### Tasks (TODO)

The **Tasks** tab under the editor lists the TODOs in every file of the project, open or not, as
CBM prg Studio's Tasks window does. A task is CBM prg Studio's `todo` directive on a line of its
own (`todo add bounds checking`, which the assembler skips), or a comment containing TODO, FIXME
or HACK (`; TODO …`, `// FIXME: …`, `/* HACK */`), so Kick Assembler sources have tasks too. In
BASIC it's a REM (`100 rem todo speed this up`). Search the list, or tick **Current file only**;
double-click a task to open its line. The tab's badge shows how many there are. The list follows
your edits (unsaved ones too) every couple of seconds.

**Add TODO…** (main menu, or right-click in the editor) puts one above the cursor's line: the
`todo` directive in CBM prg Studio projects, a `// TODO` comment in Kick Assembler ones, and in
BASIC a `rem todo` line between two line numbers (or on the end of the line when there's no
number free).

### `Operator Calc` / `Operator HiLo`

This sets how tightly `<` and `>` bind, from that line onwards:

* `Operator HiLo` (default): `<SCREENRAM+40` is `(<SCREENRAM)+40`
* `Operator Calc`: `<SCREENRAM+40` is `<(SCREENRAM+40)`. The book uses this for its row
  tables. **verified**

## Addressing

All the standard 6502 modes: `#imm`, `zp`, `zp,x`, `zp,y`, `abs`, `abs,x`, `abs,y`, `(zp,x)`,
`(zp),y`, `(abs)` (JMP only), accumulator (`asl` or `asl a`), and relative branches.

Zero page is used whenever the value fits in a byte, **including forward references**: the
assembler takes extra passes until label addresses stop changing. The book relies on this,
because `gameMemory.asm` (where the zero-page constants are defined) is the last file in the
build order. **verified**

Undocumented 6510 opcodes (`lax`, `sax`, `dcp`, …) are available with `l64asm --illegal`.

## Directives

| Directive | Notes |
|---|---|
| `byte`/`byt`/`db`/`dfb` a, b, … | bytes. A quoted string of 2+ characters gives screen codes **verified** |
| `word`/`wor`/`dw` a, … | 16-bit words, low byte first |
| `fltp` 3.14159265, … | Commodore BASIC's 5-byte floating point numbers (as in BASIC variables). Use `.` as the decimal point; a label or expression gives a whole number. Each value is the nearest 5-byte number, which matches the C64's own for most values. The ROM's number reader can be one step off in the last bit (`12345.678`) |
| `text 'string'` | screen codes. Numbers may be mixed in **verified** |
| `text "string"` | PETSCII, as CBM prg Studio's help describes (`--text screen` or `--text petscii` forces one encoding for both kinds of quotes) |
| `dcb count, a, b, …` / `dcw count, a, …` | `count` copies of the list (bytes / words) **verified** |
| `bytes`/`words` a, n*v, … | a single number gives that many zeros; `n*v` gives `n` copies of `v` |
| `bits 00001111`, `bits ....@@@@` | bytes from binary digits; `.` is 0 and `@` is 1, 8 to a byte |
| `null "str"`, `ptext "str"` | a string ending in a zero byte / starting with its length |
| `func start,end,step,expr` / `funcw` | a table of `expr` for `x` from `start` to `end` (as the Data Generator tool) |
| `random n,min,max[,seed]` / `randomw` | `n` random bytes / words; a seed gives the same values each build |
| `long`/`longs` | an error: they're 65816 only |
| `charset 1` / `charset 2` | which character set `'…'` screen codes are for: 1 (upper case and graphics, so `'A'` = `'a'` = 1) or 2 (lower and upper case, `'A'` = 65) |
| `charmap c,petscii,screen` / `charmap off` | change one character's PETSCII and screen code in `text`, `byte` and `'c'` |
| `incbin file[, skip[, length]]` | quotes optional, path relative to the source file **verified** |
| `incasm "file"` | include source, nested up to 16 deep |
| `defm NAME` … `endm` | macro, parameters `/1`…`/9` **verified** |
| `if expr` / `ifdef` / `ifndef` / `else` / `endif` | conditional assembly |
| `align n`, `org addr` | pad to a multiple of n / same as `*=` |
| `relocate addr` … `relocate off` | assemble for `addr` (labels, jumps) while storing the code where `*` is, for code copied elsewhere before it runs |
| `noloadaddr` | the program file has no 2-byte load address |
| `saveblock start,end` | the program file holds only `start`–`end` |
| `padbyte n` | the byte that fills gaps between blocks (default 0) |
| `zpopt on`/`off` | with `off`, an address written with 4 digits (`$00F3`) stays absolute, and a warning says it could be zero page |
| `warning on`/`off` | warnings for the lines in between are dropped. `jmp ($xxFF)` warns about the 6502's page-boundary bug |
| `target TGT_C64` | sets the machine (`ifdef TGT_C64` is true); others are accepted with a warning, since only the C64 is supported |
| `repeat n[,name]`, `repeat start,end[,step],name` … `endrepeat` | the lines in between, `n` times; `name` is replaced by the count (whole words). Nests |
| `debug "text"`, `debug label` | a message in the build log; `debug option auto on` shows each label as it's defined, `debug option base hex`/`decimal` |
| `export label` | puts `label`'s value into the project's BASIC files (`sys start` becomes `sys 32768`), outside strings and `rem` |
| `watch label[, comment]` | the debugger shows `label`'s byte whenever the program stops |
| `breakpoint [label] [condition]` | a breakpoint at `label` (or the next instruction) when debugging, with an optional VICE condition such as `X == 20` |
| `debugstartaddress label` | the debugger starts the program here |
| `generateto file.prg[,disk.d64[,diskname][,append]]` | the program's file name, and a disk image it's written to. `.p00` writes a PC64 file; `null` writes nothing |
| `checksum` | accepted and ignored |
| `todo text` | a task for the Tasks panel (see below); the line isn't code |
| `Operator Calc` / `Operator HiLo` | see above **verified** |

### Macros

```
defm    LIBMATH_ADD8BIT_AVA     ; /1 = address, /2 = value, /3 = address
        clc
        lda /1
        adc #/2
        sta /3
        endm

        LIBMATH_ADD8BIT_AVA score, 10, score
```

* Arguments are split on commas outside quotes and brackets, then substituted as text.
* `/n` is only a parameter when it isn't preceded by a letter, digit, `)` or `$`, so
  `lda #/1/2` divides parameter 1 by 2.
* Macros can be defined after they're used (in a later file of the build order). **verified**

## Projects

A CBM prg Studio project (`.cbmprj`) is built by assembling every file in its `<BuildList>`,
in order, as one program. Macros are shared between files, and so are labels, except that a
label defined in more than one file is local to each of them (each file sees its own), and a
label ending in `$` (`score$`) is project-wide and may be defined only once. **verified** In
CBM prg Studio, Ctrl+F5 (*Build → Project → And Run*) does this, and F5 builds only the current
file. Linux64Studio uses the same keys.

A Kick Assembler project names its main file; Kick Assembler is run on it (`java -jar
KickAss.jar`). **Project Properties → Build** can name a `KickAss.jar` kept in the project (used
instead of the one in Preferences), and add command-line options such as `-define DEBUG`. A
different program file name (for a debug build, say) is passed as `-o`. `l64asm project.l64proj`
builds a Kick Assembler project the same way, from the command line.

**Build events** are commands run before and after a project build, as in CBM prg Studio: one a
line, in the project folder. `[prg]`, `[prgName]`, `[prgDir]`, `[ProjectDir]`, `[ProjectName]` and
`[OutputDir]` are filled in. A line starting with `;` is switched off, and `echo text` writes to the
build output. The after-build commands run only when the build worked, unless you switch that
off. A command that fails fails the build. They run directly, not through a shell, so use `sh -c
"…"` for pipes and redirection. For example, to crunch the program with exomizer:

    exomizer sfx basic -n [prg] -o [prg].exo

and set the Disk Image page's **Program file to put on the disk** to `game.prg.exo`. The disk
image is written after the build events. The project's VICE options (`vice_args` in the
`.l64proj`) are added to the ones in Preferences whenever the project runs or is debugged.

## Graphics files

| File | Format | Notes |
|---|---|---|
| `.spt` sprites | XML, one `<data>` per row as a 24-bit integer | `sprites.bin` = 64 bytes per sprite **verified** |
| `.cst` characters | XML, `<charcode>` + 8 `<data>` bytes | characters that aren't listed are the **C64 ROM** ones **verified**; colours are hex `CL` (C = colour, L = luminance) **verified** |
| `.sdd` screens | XML, `<RowData>` of 7-digit hex cells | char = bits 20–27, colour = bits 12–19 |
| `.spd` SpritePad v1 | binary: `SPD`, version, counts, 3 colours, 64 bytes per sprite, 4 per animation | the 64th byte is the attribute (bit 7 multicolour, low nibble colour) and is part of SpritePad's `.bin` exports **verified** (Vol 2) |
| `.ctm` CharPad v5 | binary, as in CharPad's own format notes | charset, colour and map exports match the book's `.bin` files; all 213 `.ctm` files in the download re-save byte-identical **verified** (Vol 2) |
