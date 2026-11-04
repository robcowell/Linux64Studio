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
| `$FF`, `%1010`, `255` | hex, binary, decimal |
| `'a'` | **screen code** of the character (`'a'` = 1, `'@'` = 0, space = 32) **verified** |
| `*` | current address |
| `<expr`, `>expr` | low / high byte |
| `+ - * / % << >> & \| ^` | arithmetic and bitwise, usual precedence |
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
| `dcb count, value` | `count` copies of `value` **verified** |
| `incbin file[, skip[, length]]` | quotes optional, path relative to the source file **verified** |
| `incasm "file"` | include source, nested up to 16 deep |
| `defm NAME` … `endm` | macro, parameters `/1`…`/9` **verified** |
| `if expr` / `ifdef` / `ifndef` / `else` / `endif` | conditional assembly |
| `align n`, `org addr` | pad to a multiple of n / same as `*=` |
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
in order, as one program. All labels and macros are shared between files. **verified** In
CBM prg Studio, Ctrl+F5 (*Build → Project → And Run*) does this, and F5 builds only the current
file. Linux64Studio uses the same keys.

## Graphics files

| File | Format | Notes |
|---|---|---|
| `.spt` sprites | XML, one `<data>` per row as a 24-bit integer | `sprites.bin` = 64 bytes per sprite **verified** |
| `.cst` characters | XML, `<charcode>` + 8 `<data>` bytes | characters that aren't listed are the **C64 ROM** ones **verified**; colours are hex `CL` (C = colour, L = luminance) **verified** |
| `.sdd` screens | XML, `<RowData>` of 7-digit hex cells | char = bits 20–27, colour = bits 12–19 |
| `.spd` SpritePad v1 | binary: `SPD`, version, counts, 3 colours, 64 bytes per sprite, 4 per animation | the 64th byte is the attribute (bit 7 multicolour, low nibble colour) and is part of SpritePad's `.bin` exports **verified** (Vol 2) |
| `.ctm` CharPad v5 | binary, as in CharPad's own format notes | charset, colour and map exports match the book's `.bin` files; all 213 `.ctm` files in the download re-save byte-identical **verified** (Vol 2) |

## Not implemented (yet)

* CBM prg Studio's label-based "pBASIC"
* `GenerateTo`/`Watch` are accepted and ignored with a warning
