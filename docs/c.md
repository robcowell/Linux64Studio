# C with cc65

Linux64Studio builds C programs for the C64 with [cc65](https://cc65.github.io/), as it builds
Kick Assembler projects with KickAss.jar: cc65 is an outside tool, and the IDE runs it, shows its
errors, runs the program in VICE and debugs it at the level of C lines.

Install cc65 first:

```sh
sudo apt install cc65
```

## A C project

**File → New → Project…** and choose **C (cc65)**. A new project gets a `main.c` that prints a
message and flashes the border until a key is pressed, so **Ctrl+F5** (Build Project and Run) shows
it working straight away.

A C project builds **one program** from the files on its **build list**: C files (`.c`, compiled by
cc65) and assembler files (`.s`, assembled by ca65), linked by ld65 with the C64 runtime library.

* Right-click a file in the tree for **Add to Build** / **Remove from Build**, or set the list in
  **Project → Properties…**. Headers (`.h`) aren't on the list: `#include` brings them in.
* **File → New → C File…** makes a `.c` (added to the build list) and **C Header File…** a `.h`
  with an include guard.
* Building puts the program in the project's `build` folder, with its object files (`build/obj`), a
  map file, a VICE label file and ld65's debug file. Nothing is written beside your sources.

### C files you already have

To work on C you already have, make the project in its folder: in New Project, set **Location** to
that folder and switch off **Make a folder for it**. Nothing is overwritten: the build list starts
empty (or with `main.c`, if there is one), and you add the program's files to it.

Code shared with other programs (a library in `../lib`, say) goes in **Project → Properties… →
Build → More source folders**. Those folders show in the file tree (as `../lib`), their `.c` files
can go on the build list, and they're include paths for `#include "…"` and ca65's `.include`.

For example, one of the ultimateii-dos-lib samples, built by its script with

```sh
cd src/samples
cl65 -O -t c64 ../lib/ultimate_lib.c u-shell.c -o u-shell.prg
```

is a project in `src/samples` with the build list `../lib/ultimate_lib.c`, `u-shell.c`, the source
folder `../lib` and the options `-O`. It builds byte-for-byte the same program. The other samples
can be more **programs** in the same project (Project → New Program…), each with its own build
list, and **Build → Build All Programs** puts them all on one disk image, as the library's build
script does ([several programs](dialect.md#several-programs-in-one-project)).

### Options

**Project → Properties… → Build** has the compiler options, passed to every compile:
`-O` (optimise, the default for a new project), `-Oirs` (more), `-DNAME` or `-DNAME=value`
(defines), `-W …` (warnings) and so on. Every file is compiled with `cl65 -t c64 -g`: the target is
always the C64.

## Building and errors

**F7** (Build Project) compiles each file on the build list, then links them. Errors and warnings
from cc65, ca65 and ld65 are listed under **Build Output**; click one to go to its line. A function
or variable that's declared but never defined is reported by name (``'g' isn't defined anywhere
(used in main.c)``): usually a file missing from the build list.

**Shift+F7** (Build Current File) compiles just the file you're editing, to check it, without linking.
**F5** (Build and Run the current file) builds and runs the whole project, since one C file isn't a
program on its own.

## Running and debugging

**Ctrl+F5** runs the program in VICE. **Shift+F5** debugs it, as an assembler program is
debugged ([debugger](debugger.md)):

* Breakpoints go on C lines (click the line number, or F9) and are listed in the **Breakpoints**
  tab with the address each stops at. A breakpoint on a line that makes no code (a declaration, a
  comment, a brace) stops at the next line that does.
* When the program stops, the editor shows the C line it's on, and the Debugger tab the registers,
  memory and disassembly, with the program's labels (C functions and globals have cc65's leading
  underscore: `_main`).

### Variables

While a C program is stopped, the Debugger tab's **Variables** list (above Memory) shows the
current function's parameters and local variables, then the program's global variables, each with
its type, its value and its address. A value that changed since the last stop is highlighted, as
changed registers are.

**Double-click a variable to set it** (or to see its bytes: **Show in Memory**). Type the new value
as its type takes it, and **Set** writes it into the C64's memory; the program carries on with it.

* Numbers in decimal (`-2`), `$hex`, `0x` hex, `%binary`, or a character (`'a'`). A value that
  doesn't fit the type (300 in an `unsigned char`, -1 in an `unsigned int`) is refused as you type.
* Pointers as an address (`$C000`) or `NULL`.
* `char` arrays as text in quotes (`"hi there"`), stored as cc65 stores a string (PETSCII, with the
  0 at the end, the rest of the array cleared); other arrays as items with commas (`1, 2, 3`).
* Structs, and variables whose type isn't known, as their bytes in hex (`05 00 FE FF`).

* Values are shown as their types say: numbers in decimal and hex (a `char` with its character),
  pointers as addresses (or `NULL`), `char` arrays as text, other arrays and structs as `{…}`.
* A local declared further down the function shows *not declared yet* until its declaration has
  run (cc65 makes room for it there), and one in a block that has ended, *out of scope*.
* On a function's first line its arguments aren't in place yet: step once (F10).
* Locals are read from cc65's C stack, which is exact at the start of a line, where breakpoints
  and stepping by C line stop. Part-way through a line (after Ctrl+F10) they may be off, and the
  list says so.
* cc65 doesn't record C types in its debug information, so they're read from your source
  declarations (including `#define`d array sizes, `typedef`s, structs and `stdint.h` types). A
  variable whose declaration can't be read is shown as bytes. `static` variables inside a function
  aren't listed (cc65 gives them no name in the debug information); `register` variables show the
  value saved on the C stack.

### Stepping by C line

On a line of C, **F10** (Step Over) and **F11** (Step Into) go to the next line of C, as a C
debugger does, not the next instruction:

* **F10** runs the whole line, calls and all, and stops on the next line that runs: the line below,
  or back at the top of a loop. A function the line calls runs to its end without stopping, unless
  there's a breakpoint in it.
* **F11** goes into a C function the line calls and stops on its first line. Calls to cc65's
  runtime library and the KERNAL (which have no C source) run to their end, as with F10.
* Either way, the program runs at full speed while it's on the line, so a busy loop on one line
  takes no longer than it would anyway. A line that waits (for a key, say) waits: the Debugger tab
  says *Stepping to the next C line…*, and **Pause** stops it where it's got to.
* Stepping past the end of a function stops on the line that called it.
* **Shift+F11** (Step Out) runs to the end of the function and stops in the caller.
* **Ctrl+F10** and **Ctrl+F11** step one instruction (over or into a JSR), for when you want to see
  the 6502 code a line makes. From code with no line of C (cc65's runtime, after Ctrl+F11 into it),
  F10 and F11 run on to the next line of C. In your own assembler files (`.s`), F10 and F11 step by
  instruction, as in an assembler project.

## In the editor

`.c` and `.h` files have C syntax highlighting, and the editor knows the program's C:

* **Auto-complete** offers the parameters and locals of the function you're in, then the program's
  functions, global variables, macros, types and enum constants (this file's first), then C's
  keywords. Ctrl+Space opens the list at any time.
* **Go to Definition** (F12, or Ctrl+click) goes to where a name is defined: a function's body
  rather than its prototype, a variable's definition rather than an `extern`, or the parameter or
  local of the function you're in. On an `#include` line it opens the header: `"…"` from the
  file's folder, then the project's source folders; `<…>` from those and cc65's own headers (in
  `/usr/share/cc65/include`, or `$CC65_INC`). Alt+Left goes back.
* **Hovering** over a name says what it is and where it's defined, and for a global variable its
  address in the last build.
* The **Project Information** panel's tabs become **Functions** (with their addresses after a
  build), **Variables** (the globals, with their addresses) and **Types & Macros** (typedefs,
  structs, enums and their constants, and `#define`s with their values).
* Only the program's own `.c` files (those on the build list) and the headers are read, so another
  program's `main()` in the same folder doesn't get in the way. An assembler file calling C
  (`jsr _twice`) finds the C function too.

Find, Replace, Find in Files, the Tasks list (`// TODO`, `/* FIXME */`) and Go to Line work as for
assembler.

### Assembler files (ca65)

In a C project, assembler files (`.s`, `.asm`, `.inc`) are ca65's, cc65's assembler, and the editor
treats them that way (in other projects a `.s` file is CBM prg Studio or Kick Assembler source, as
before):

* ca65 syntax highlighting: control commands (`.proc`, `.segment`, `.importzp`, `.lobyte`…),
  `name:` labels, `@cheap` local labels, unnamed `:` labels and their `:+` / `:-` references, and
  numbers in `$hex`, `%binary` and decimal.
* Auto-complete offers ca65's control commands (type the dot: `.seg` gives `.segment`), the
  instructions and the file's names.
* Go to Definition, hover and the Project Information panel know ca65's definitions: labels and
  `.proc`s (under Functions), `@cheap` locals (the one belonging to the label above), `=`, `:=`,
  `.set` and `.define` (Variables), and `.macro`, `.struct`, `.union`, `.enum` and `.scope`
  (Types & Macros). ca65's names are case-sensitive. F12 on `jsr _twice` goes to the C function
  `twice`, and on an `.include` or `.incbin` line opens the file, looking in the file's folder, the
  project's source folders and cc65's own `asminc` folder.

Strings are PETSCII on the C64: with the C64's start-up character set, lower-case letters in a
string show as capitals, and capitals as graphics characters.
