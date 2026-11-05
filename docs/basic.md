# BASIC V2 in Linux64Studio

`.bas` files are Commodore 64 BASIC V2 source. Build them like any other project file:
Ctrl+F5 builds the project and runs it, F5 builds and runs just the current file.

## Source format

```
10 print "{clear}{white}hello, world!"
20 for i=0 to 15:poke 53280,i:next
30 goto 20
```

* Every line starts with a line number (0–63999). Lines are sorted by number when you build,
  with a warning if they were out of order. A number used twice is an error.
* Keywords and variable names can be in upper or lower case. Inside strings and REM, lower
  case gives the C64's normal letters and upper case gives the shifted characters (graphics
  in the default character set), the same as VICE's `petcat`.
* `π` (or `{pi}`), `£`, `^` (↑) and `_` (←) map to their PETSCII characters.

### Control codes

Put these in braces inside strings. Case doesn't matter.

| Code | Names you can use |
|---|---|
| `$93` | `{clear}` `{clr}` `{cls}` |
| `$13` | `{home}` |
| `$11` `$91` `$1D` `$9D` | `{down}` `{up}` `{right}`/`{rght}` `{left}` |
| `$12` `$92` | `{reverse on}`/`{rvon}`/`{rvs on}`, `{reverse off}`/`{rvof}` |
| colours | `{black}` `{white}` `{red}` `{cyan}` `{purple}` `{green}` `{blue}` `{yellow}` `{orange}` `{brown}` `{light red}` `{dark grey}` `{grey}` `{light green}` `{light blue}` `{light grey}`, and petcat's `{blk}` `{wht}` `{cyn}` `{pur}` `{grn}` `{blu}` `{yel}` `{orng}` `{brn}` `{lred}` `{gry1}` `{gry2}` `{lgrn}` `{lblu}` `{gry3}` |
| `$85`–`$8C` | `{f1}` … `{f8}` |
| `$14` `$94` | `{delete}`/`{del}`, `{insert}`/`{inst}` |
| `$0E` `$8E` | `{lower case}`/`{swlc}`, `{upper case}`/`{swuc}` |
| Commodore-key graphics | `{cbm-a}` … `{cbm-z}`, `{cbm-+}` `{cbm--}` `{cbm-@}` `{cbm-*}` `{cbm-£}` |
| SHIFT graphics | upper-case letters, or `{shift-a}` …; also `{shift-+}` `{shift--}` `{shift-@}` `{shift-*}` `{shift-£}` `{shift-^}` |
| any byte | `{$93}` or `{147}` |
| repeats | `{3 down}` or `{down*3}` (`{a*3}` for a character) |

### Code styles: BasText and Tok64

CBM prg Studio writes control codes in one of two styles, BasText or Tok64. Linux64Studio reads
both, and its own, whichever is chosen. **Preferences → BASIC → Control codes in BASIC** chooses
how they're written when a `.prg` is listed (and `l64bas --list --codes standard|bastext|tok64`)
and in the Screen Code Builder, which also has its own choice.

| | Linux64Studio | BasText | Tok64 (VICE's petcat) |
|---|---|---|---|
| clear, colours, reverse | `{clear}` `{yellow}` `{reverse on}` | `{clear}` `{yellow}` `{reverse on}` | `{clr}` `{yel}` `{rvon}` |
| Commodore, SHIFT, CTRL keys | `{cbm-a}` `{shift-£}` `{$01}` | `{cm a}` `{sh pound}` `{ct a}` | `{CBM-A}` `{SHIFT-POUND}` `{CTRL-A}` |
| £, ←, π | `£` `_` `{pi}` | `{pound}` `{arrow left}` `{pi}` | `\` `_` `~` |
| other codes | `{$82}` | `{130}` | `{$82}` |
| repeats | `{3 down}` | `{down*3}`, `{a*3}` | `{down*3}`, `{a*3}` |

The Tok64 names are exactly the ones VICE's petcat writes (checked against petcat for all 256
codes, except a quote, written `{$22}` so it doesn't end the string). CBM prg Studio's BasText
table isn't published: these are the names its program uses (`white`, `reverse on`, `light
blue`, `cm k`, `sh pound`, `ct a`, `pound`, `arrow left`, `sh space`, `sh return`,
`lowercase`, `escape`, three-digit numbers for the rest), so BasText written by CBM prg Studio
may differ in places; it's read either way. Runs are written as CBM prg Studio's Screen Code
Builder writes them, `{down*3}`.

## How lines are tokenized

The tokenizer copies the C64 ROM's CRUNCH routine, so a program behaves exactly as if you had
typed it in on a real machine:

* Keywords are found wherever they appear, even inside variable names: `score` contains `or`,
  just as on the C64 (where `SCORE=1` gives `?SYNTAX ERROR`).
* `?` is `PRINT`.
* Nothing is crunched inside quotes or after `REM`. `DATA` is left alone up to the next `:`.
* Spaces are kept, except the ones between the line number and the text.

Output is checked against VICE's `petcat -w2` (`tests/test_basic.py`). There are two
differences, both because the real C64 does it this way: `?` becomes `PRINT` (petcat leaves a
`?`), and `π` in UTF-8 source is the single PETSCII `π` byte.

## Automatic line numbers

As in CBM prg Studio, pressing Return at the end of a line in a `.bas` file starts the next line
with its number: the step after this line's (10 by default), or, between two lines, a number in
between them if there's one free (Return after `10` with `20` below gives `15`). In the middle of
a line, Return just splits it; **Shift+Return** adds a line without a number. **Preferences →
BASIC** turns it off and sets the step. It's one undo step, and pBASIC files aren't numbered.

## Renumbering

**Tools → BASIC → Renumber…** (or `l64bas --renumber`) renumbers the whole file and updates
line numbers after `GOTO`, `GO TO`, `GOSUB`, `THEN`, `ON … GOTO/GOSUB`, `RUN` and `LIST`.
References inside strings, REM or DATA are left alone. A reference to a line that doesn't
exist is kept, with a warning. Ctrl+Z undoes the whole renumber.

## pBASIC: BASIC without line numbers

A `.pbas` file (*New → New pBASIC File…*) is CBM prg Studio's pBASIC: BASIC V2 with labels
instead of line numbers. A line holding only `@name` labels the line after it, and `goto @name`,
`gosub @name`, `then @name`, `on x goto @a,@b`, `run @name` and `list @name` jump to it:

```
rem automatic color bars
print chr$(147)
@loop
print chr$(18); "     ";
cl = int(8*rnd(1))+1
on cl goto @col1,@col2
@col1
print chr$(5);: goto @loop
@col2
print chr$(28);: goto @loop
```

When it's built, every line is numbered (10, 20, 30, … by default) and the numbers go in place of
the labels, so this becomes `30 print chr$(18)…` and `60 print chr$(5);: goto 30`. Labels are any
case; a label must be on a line of its own; an `@` inside a string, REM or DATA is just a
character. Errors point at the pBASIC line.

**Preferences → BASIC** sets the first line number, the increment and the label prefix (`@`
unless you change it), and *Preview generation* opens the numbered BASIC in a read-only
*name (generated).bas* tab after each build. Right-click → *Preview Generated BASIC* shows it at
any time.

`namespace name` … `namespace end` makes the labels in between local to that block, so each
block can have its own `@loop`. Two additions to CBM prg Studio's version: code in a namespace
can jump to a global label (one defined outside any namespace) when it has no label of that
name itself, and `@block.name` jumps to a label in another namespace.

Unlike CBM prg Studio, a `.pbas` file can be in a project's build list, like a `.bas` file, and
`l64bas game.pbas` builds one from the command line (`--start`, `--step`, `--prefix`;
`--preview` prints the numbered BASIC).

### Converting a BASIC program

As in CBM prg Studio's tutorial 17: paste the numbered program into a `.pbas` file, right-click a
line number after a `GOTO` or `GOSUB` and choose *Create Label…*. Name it, and the label goes
above that line, and into every jump to it. When every jump target has a label, right-click →
*Remove Line Numbers*. It warns about any jump still going to a number, or if there are no
labels at all.

Or in one step: right-click in a `.bas` file → *Convert to pBASIC* makes a new `.pbas` file with
a label (`@line100`) for every line a jump goes to.

Tools that write numbered BASIC (Code Snippets, the SYS() call generator, …) insert it into a
pBASIC file without its line numbers, with labels for any jumps.

## Reformatting

**Reformat BASIC…** (**Tools → BASIC → Reformat…**, or right-click in a BASIC file) is CBM prg Studio's Reformat BASIC
Code:

* **General formatting:** a space after each line number; blank lines removed; quoted strings and
  REMs converted to lower or upper case ({codes} are left alone; in a string, capitals are the
  shifted characters, so this changes what's printed).
* **Source compression:** REM statements removed (a line that's only a REM goes, unless a GOTO
  goes to it: then it's kept as `rem`); spaces removed, outside strings (and in REMs if asked);
  zeros taken out of DATA (`data 0,0.5` becomes `data ,.5`, which READ reads the same); keywords
  abbreviated.
* **Expand code:** keywords in full, with a space round them (`?a:pO53280,0` becomes
  `print a:poke 53280,0`).
* **Create backup file** saves the text as it was to `name.bas.bak`.

Right-click → **Compress** writes keywords abbreviated, as the C64 manual lists them (`?` for
PRINT, `pO` POKE, `gO` GOTO, `fO` FOR, `goS` GOSUB, `pR` PRINT#…; a few, like IF and ON, have
none), and **Uncompress** writes them in full, in lower case or (Preferences → BASIC) upper.

Only what needs changing is changed: the rest of each line stays as you wrote it. Each changed
line is tokenized before and after, and if it would do anything different (beyond what was asked
for, such as a string's case) it's left as it was and marked: removing the space from
`a=t an` would make it `a=tan`. Everything is one Ctrl+Z. pBASIC files work too.

Abbreviations are read as the C64 reads them, so `pO53280,0` builds: a lower-case letter then a
capital ends the keyword, and the ROM's keyword order decides which (`pR` is PRINT#, not PRINT).
A word all in capitals is read in full (`PRINT`).

## Your own tokens (token files)

As CBM prg Studio's user-defined tokens: a BASIC file that starts with

```
tokenfile mytokens.tkn
```

is tokenized with the keywords in that file (in the BASIC file's folder; `.tkn` is added if there's
no extension), so a BASIC extension's keywords (Super Expander's `GRAPHIC`, a cartridge's own)
build, or a keyword can be given another token. The file is CSV, `KEYWORD, token in hex[,
abbreviation]` a line, with `#` comments:

```
# super expander only
GRAPHIC, CD
SCNCLR, CE
CIRCLE, CF
```

Its keywords are tried first, in the file's order (put a keyword that starts another first, as
`PRINT#` before `PRINT`), then BASIC V2's that it doesn't name, so a file of just an extension's
keywords is enough. A token can be two bytes (`FE02`), as the Mega65's are. Abbreviations work as the
C64's do (`gR` for GRAPHIC). Renumbering, pBASIC, reformatting and folding keep the `tokenfile`
line where it is.

**Tools → BASIC → Create Token File…** writes BASIC V2's table (with abbreviations) to a `.tkn`
in the project folder, opens it, and copies the `tokenfile` line to paste at the top of a BASIC
file. CBM prg Studio's tutorial 18 (give PRINT the token `A1` and see it in the `.prg`) works as it
describes.

## Listing programs

Opening a `.prg` (or *List BASIC Program…*) lists it as a new `.bas` file. Control characters
come out as `{names}`, and repeated ones as `{3 down}`. For a machine-code program you see its
BASIC loader, e.g. `10 sys (2064)`.

## BASIC and assembly together

A project's build list can hold `.bas` and `.asm` files. The BASIC program is placed at
`$0801`, and the assembled code wherever its `*=` puts it. It's an error if they overlap.
For example, `10 sys 49152` in `main.bas` with `*=$c000` code in `code.asm`.

## Screen Code Builder

**Tools → Screen Code Builder** builds the strings that are awkward to type: colour
changes, cursor moves, reverse video, and the graphics on the Commodore and SHIFT keys.

* Type text, or use one of the three tabs, as in CBM prg Studio:
  * **Virtual Keyboard**: a C64 keyboard to click. Each key types what it would on a C64 (the
    KERNAL's own decode tables): its face shows the Commodore and SHIFT graphics, and on 1–8 the
    colours CTRL and C= give. Click SHIFT, C= or CTRL for the next key, or double-click one to lock
    it; SHIFT LOCK locks SHIFT; SHIFT with C= switches the character set. Hover over a key to see
    all it types. You can type on it too: letters, digits and punctuation, the cursor keys,
    Home (CLR/HOME), Backspace (INST/DEL), F1–F8, with Tab as CTRL and Ctrl as C=, as in CBM prg
    Studio (Tab+8 is yellow, Ctrl+A is `{cbm-a}`).
  * **Key Map**: the **colour swatches**, the **keys** (CLR, HOME, cursor keys, RVS ON/OFF,
    RETURN, DEL, INST, case switch, F1–F8) and the **graphics**, drawn from the C64's character
    ROM (hover for the key, e.g. `CBM-A`).
  * **Key Codes**: every named code with the keys that type it and its value; double-click one.
* The **Actual** line shows the text as it comes out, with runs counted (`{down*4}`), in the
  chosen code style: Linux64Studio's, BasText or Tok64 (see Code styles above). The keys type in
  that style, and the BASIC output uses it.

  Everything is written in the BASIC notation above.
* **On the C64** shows what `PRINT`ing it does on a real screen: colours, cursor moves, reverse,
  clearing, deleting and inserting, scrolling, and the case switch. Set the border, background
  and starting text colour to match your program. A block shows where the cursor ends up.
* Get it as:
  * a **BASIC PRINT statement**, with a line number if you like;
  * **PETSCII bytes** to print with the KERNAL's `CHROUT` (`$FFD2`), ending with 0 if wanted;
  * **screen codes** (and colour RAM bytes) for the rows it fills, to copy straight into
    screen memory. Control codes aren't stored there; this is what they leave on the screen.

  Byte output uses the project's syntax (`byte`, or `.byte` for Kick Assembler). **Insert into
  Editor** puts it on its own line in the source file you last worked on.

The preview follows the KERNAL's screen editor. It was checked against VICE, including the
colour RAM under blank cells (clearing fills it with the current text colour) and the
character set chosen in `$D018`. With `L64S_VICE_TESTS=1`, `tests/test_screencodes.py` runs that
comparison itself.

## Code Snippets

**Tools → Code Snippets** is a library of small routines to insert into a program, as in CBM prg
Studio. The snippets are grouped by CBM's six types: Sprites, Characters, Hi-res, Sound, Misc and
Machine Code. Machine Code snippets are assembler; all the others are BASIC. Search filters by
description, code or type. Double-click a snippet, or press **Insert into Editor**, to insert it
into the last source file you used. **Copy** puts it on the clipboard.

BASIC snippets are written without line numbers. They're numbered from **Start line** in steps
of **Step**; **After the program** starts after the last line of the BASIC file you're inserting
into. Snippets can use labels: start a line with `!1` to `!9`, and write `!n` after GOTO,
GOSUB, THEN or ON … GOTO to jump to it. For example `!1 get k$ : if k$="" then !1` becomes
`1000 get k$ : if k$="" then 1000`. Labels inside strings and REMs are left alone, and using a
label no line has is an error. The numbered lines go where their numbers belong in the file, not
at the cursor. If any of their line numbers are already used, nothing is inserted and you're
told which.

Snippets in CBM prg Studio's capitals (`POKE V+21,…`) become listing case (`poke v+21,…`) when
inserted, because capitals are shifted characters in a BASIC listing. Machine Code snippets are
in CBM prg Studio's syntax. In a Kick Assembler project they're converted as they're inserted:
labels get a colon, `;` becomes `//`, `byte`/`word`/`text` become `.byte`/`.word`/`.text`, and
`NAME = value` becomes `.const`. That's enough for simple snippets; macros aren't converted.

Edit a snippet's description, type or code in place. **+** adds one, and the other buttons
duplicate and delete. Save the library with Ctrl+S or the save button. It's kept in
`~/.config/linux64studio/snippets.xml`, which starts as a copy of the built-in snippets. The ⋮
menu has three items: **Import** merges another snippets file, such as CBM prg Studio's own
`Snippets.xml` from its install folder; **Export** writes the library out; **Add back the
built-in snippets** restores any you've deleted. Snippets already in the library (same type and
description) aren't imported twice. The file format is CBM prg Studio's, so a library can go
back to CBM prg Studio too.

The 37 built-in snippets were written for Linux64Studio. They don't include CBM prg Studio's
own, which you can import from your copy. `tests/test_snippets.py` checks that every BASIC snippet
tokenises and lists back unchanged, and every Machine Code snippet assembles. Its VICE tests
(`L64S_VICE_TESTS=1`) run some of them: copying the character ROM to RAM, plotting a point in
a bitmap, and the raster interrupt.

## SYS() call generator

**Tools → SYS() Call Generator** writes the one-line BASIC program that starts a machine code
program when you RUN it, as `byte` lines for the top of an assembler source. This is the same
thing the book's chapters start with (`10 SYS (2064)`). It has three styles, as in CBM prg Studio:

* **Decorated**: `10 SYS (2064)`. With the defaults it gives exactly the book's 15 bytes.
* **Plain**: `10 SYS2061`, one byte shorter.
* **Obfuscated**: the line is `10 SYS2094:REM` followed by DEL characters and a message. When
  the program is LISTed, the DELs rub out the SYS on screen and only the message shows. RUN
  still runs the SYS. The message can use control codes such as `{white}`, as in the Screen Code
  Builder, and can be up to 60 characters.

Choose the BASIC line number and where the program starts. **Right after the SYS line**, the
usual choice, works out the address, which depends on its own number of digits. **At** takes
`$hex`, decimal, or a label from the last build (such as `start`). If the program starts well
above the SYS line, the bytes between are padding in the `.prg`, which makes it bigger. The
source ends with `*=` the start address, so your code follows on.

**Insert at Top** puts the stub at the start of the last source file you used, and **Insert at
Cursor** puts it at the cursor. It won't insert into a file that already has code at `$0801`, or
into a BASIC file. In a Kick Assembler project the output uses `.byte` and `//` comments
(Kick Assembler's own `BasicUpstart2` macro does the same job).

`tests/test_sysgen.py` checks the bytes (the decorated stub is the book's), reads the SYS address
back, and assembles the source. Its VICE tests (`L64S_VICE_TESTS=1`) RUN each style and check
that the machine code ran. They also LIST the obfuscated line and check the screen shows only
the message.

## String Formatter

**Tools → String Formatter** splits a long string into lines of a set length, as in CBM prg Studio.
Type or paste the text into **Source**; the character count is how long it is on the C64 (a
control code such as `{white}` is one character). **Output** shows the result as you type:

* **BASIC**: lines that build the string in a variable, starting at **Start line** in steps of
  **Step**: `100 a$="…"`, then `110 a$=a$+"…"`. Without **Initialise**, every line adds to the
  variable. A `"` can't go in a BASIC string, so it's an error. You're warned if a line is longer
  than the 80 characters the C64 lets you type, or the string is longer than BASIC's 255.
* **Assembler**: `text` lines, either as **PETSCII** (`text "…"`, for printing with CHROUT) or
  **screen codes** (`text '…'`, for writing straight to screen memory). Control codes become
  numbers between the quoted runs (`text $05, "hello"`), so they only work in PETSCII. An
  optional **Label** goes above the lines. In a Kick Assembler project it writes `.text`, with
  an `.encoding` line for PETSCII and one to put the default (screen codes) back.

**Characters per line** sets the length of each piece. **Keep words together** ends pieces after
a space where it can. A control code is never split. The output starts as BASIC if the last
file you edited is BASIC, and as assembler otherwise, as in CBM prg Studio. You can switch it.

**Convert** changes the source text. **Upper**, **Lower** and **Mixed** (sentence case) leave
control codes alone. Remember that lower case letters are the C64's normal letters, and
capitals are the shifted ones. **Find** lists the matches of a regular expression and selects
the first. **Replace All** replaces them; `\1` works in the replacement. Each change is one
undo step (Ctrl+Z in the source box).

**Copy** puts the output on the clipboard, and **Insert into Editor** puts it at the cursor of
the last source file you used, if it's the same kind (BASIC or assembler).

`tests/test_strformat.py` checks the splitting, case changes, find and replace, and both
outputs, and that they tokenise and assemble. With `L64S_VICE_TESTS=1` it runs them in VICE: the
BASIC program PRINTs the string, and the PETSCII text is printed with CHROUT, and the screen
shows the message exactly.

## Statistics

**Tools → BASIC → Statistics** breaks down the BASIC file you're editing, as CBM prg Studio's tool
does. At the top: how many lines it has, where it sits in memory, its size, and how much of
the 38911 bytes of BASIC memory is left. Then:

* **Variables**: each variable the program sets, with its type and the line it's first set on,
  and how (`=`, `for`, `input`, `read`, `get`, `dim`). As in CBM prg Studio, only variables that
  are given a value are listed here. Only the first two characters of a name count on the C64,
  so each one also shows the name the C64 really uses (`LI%` for `lives%`).
* **Duplicate Variables**: different names that are the same variable: `score` and `scale`
  are both `SC`.
* **Used but never set**: names that are read but never given a value. On the C64 they're 0
  (or empty), which usually means a typing mistake.
* **Problems**:
  * Names with a keyword inside, which the C64 reads as that keyword: `score` is `SC OR E`,
    `hiscore` is `HISC OR E`, and `points` is `PO INT S`. A keyword at the start of a word isn't
    listed, because that's how crunched code is written (`FORT=1TO10`).
  * GOTO, GOSUB, THEN, ON … GOTO, RUN and LIST to lines that don't exist.
  * Setting the system variables `ST` or `TI`. `TI$` can be set.

Click an entry to go to its line. **Refresh** reads the file again (for example after editing
it). **Copy Report** and **Export…** give the whole breakdown as text.

The program is read the way the C64 reads it: it's tokenised first, so keywords are found where
the ROM finds them, and strings, REM, DATA and `DEF FN` parameters aren't variables.
`tests/test_basic_stats.py` checks each part. Its VICE test (`L64S_VICE_TESTS=1`) confirms the
facts on a C64: `scale` and `sc` are the same variable, `score=5` gives `?SYNTAX ERROR`, and so
does `ti=5`.
