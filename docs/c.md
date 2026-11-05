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
folder `../lib` and the options `-O`. It builds byte-for-byte the same program. A folder can hold
several projects, one for each program.

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
* Stepping (F10, F11, Shift+F11) is by instruction, not by C line. C variables aren't shown by name:
  look them up in the map file, or watch their memory.

## In the editor

`.c` and `.h` files have C syntax highlighting. Find, Replace, Find in Files, the Tasks list
(`// TODO`, `/* FIXME */`), Go to Line and the file tools work as for assembler. Auto-complete,
the Project Information panel and Go to Definition are for assembler and BASIC, so they don't
offer anything in C yet.

Strings are PETSCII on the C64: with the C64's start-up character set, lower-case letters in a
string show as capitals, and capitals as graphics characters.
