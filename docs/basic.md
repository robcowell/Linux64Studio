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
| any byte | `{$93}` or `{147}` |
| repeats | `{3 down}` or `{down*3}` |

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

## Renumbering

*Renumber BASIC…* in the menu (or `l64bas --renumber`) renumbers the whole file and updates
line numbers after `GOTO`, `GO TO`, `GOSUB`, `THEN`, `ON … GOTO/GOSUB`, `RUN` and `LIST`.
References inside strings, REM or DATA are left alone. A reference to a line that doesn't
exist is kept, with a warning. Ctrl+Z undoes the whole renumber.

## Listing programs

Opening a `.prg` (or *List BASIC Program…*) lists it as a new `.bas` file. Control characters
come out as `{names}`, and repeated ones as `{3 down}`. For a machine-code program you see its
BASIC loader, e.g. `10 sys (2064)`.

## BASIC and assembly together

A project's build list can hold `.bas` and `.asm` files. The BASIC program is placed at
`$0801`, and the assembled code wherever its `*=` puts it. It's an error if they overlap.
For example, `10 sys 49152` in `main.bas` with `*=$c000` code in `code.asm`.
