"""BASIC V2 keyword help: what each keyword does, its form and an example, and which keyword is at
a place in a line (as the ROM's tokenizer would find it there, so `fori=1to10` has FOR and TO).

Keywords are in listing notation (lower case), as Linux64Studio writes BASIC. Forms use
<angle brackets> for what you supply and [square brackets] for what may be left out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenizer import _source_bytes, match_keyword

STATEMENT, FUNCTION, OPERATOR, PART = "statement", "function", "operator", "part of a statement"


@dataclass(frozen=True)
class Keyword:
    name: str            # as written: print, chr$, tab(
    kind: str            # STATEMENT, FUNCTION, OPERATOR or PART
    form: str            # how it's written
    text: str            # what it does
    example: str = ""
    abbrev: str = ""     # how it's abbreviated when typed on the C64 (the capital is shifted)

    @property
    def title(self) -> str:
        return self.name.upper().rstrip("(")


def _k(name, kind, form, text, example="", abbrev=""):
    return Keyword(name, kind, form, text, example, abbrev)


KEYWORDS: dict[str, Keyword] = {k.name: k for k in [
    _k("abs", FUNCTION, "abs(<number>)", "The number without its sign: abs(-3) is 3.",
       "10 d = abs(x1 - x2)", "aB"),
    _k("and", OPERATOR, "<a> and <b>",
       "In a condition, true only when both sides are. On numbers it works bit by bit on 16-bit "
       "whole numbers (-32768 to 32767), so it also masks bits: peek(53265) and 127 clears bit 7.",
       "10 if x > 0 and x < 40 then print \"on screen\"", "aN"),
    _k("asc", FUNCTION, "asc(<string>)",
       "The PETSCII code of the string's first character. An empty string gives ?ILLEGAL QUANTITY "
       "ERROR, so test len() first when it may be empty.",
       "10 get k$: if k$ <> \"\" then print asc(k$)", "aS"),
    _k("atn", FUNCTION, "atn(<number>)", "The arctangent of the number, in radians (-π/2 to π/2).",
       "10 a = atn(1) * 4: rem a is now π", "aT"),
    _k("chr$", FUNCTION, "chr$(<code>)",
       "The character with this PETSCII code (0-255). Control codes work too: chr$(147) clears the "
       "screen, chr$(13) is Return, chr$(34) a quote mark.",
       "10 print chr$(147); \"hello\"", "cH"),
    _k("close", STATEMENT, "close <file number>",
       "Closes a file opened with open. Close every file you write to, or the last of what was "
       "written may never reach the disk.",
       "10 open 2,8,2,\"scores,s,w\": print#2, s: close 2", "clO"),
    _k("clr", STATEMENT, "clr",
       "Clears every variable and array, and the def fn functions, and forgets open files without "
       "closing them. The program itself stays.",
       "10 clr", "cL"),
    _k("cmd", STATEMENT, "cmd <file number> [, <things to print>]",
       "Sends what print (and list) would put on the screen to an open file instead, a printer say. "
       "Finish with print# to the file before closing it.",
       "10 open 4,4: cmd 4: list", "cM"),
    _k("cont", STATEMENT, "cont",
       "Carries on a program that was stopped by stop, end or the RUN/STOP key, from where it "
       "stopped. After the program's been changed it gives ?CAN'T CONTINUE ERROR.",
       "cont", "cO"),
    _k("cos", FUNCTION, "cos(<angle>)", "The cosine of an angle in radians.",
       "10 x = 160 + 50 * cos(a)", ""),
    _k("data", STATEMENT, "data <value> [, <value> ...]",
       "Numbers and strings for read to take, in order through the program. A string with a comma, "
       "colon or leading space needs quote marks. The line is never run itself.",
       "100 data 1, 2, 3, \"three, four\"", "dA"),
    _k("def", STATEMENT, "def fn<name>(<variable>) = <expression>",
       "Defines a one-line function of one number, called as fn<name>(...). Only in a program, not "
       "typed directly; the definition must run before the function is used.",
       "10 def fnr(x) = int(rnd(1) * x) + 1\n20 print fnr(6)", "dE"),
    _k("dim", STATEMENT, "dim <array>(<size> [, <size> ...]) [, ...]",
       "Makes an array, numbered from 0 to the size. An array used without dim has 0 to 10 in each "
       "dimension. An array can only be made once: again gives ?REDIM'D ARRAY ERROR.",
       "10 dim x(20), n$(5), b%(7,7)", "dI"),
    _k("end", STATEMENT, "end",
       "Ends the program and returns to READY. without a message. Cont carries on after it.",
       "999 end", "eN"),
    _k("exp", FUNCTION, "exp(<number>)", "e (2.71828...) to the power of the number. Above about 88 "
       "gives ?OVERFLOW ERROR.", "10 y = exp(1)", "eX"),
    _k("fn", PART, "fn<name>(<number>)", "Calls a function made with def fn.",
       "20 print fnr(6)", ""),
    _k("for", STATEMENT, "for <variable> = <start> to <end> [step <amount>]",
       "Starts a loop that runs down to next, adding step (1 if left out) to the variable each time "
       "until it passes the end. The loop always runs at least once.",
       "10 for i = 1 to 10 step 2: print i: next i", "fO"),
    _k("fre", FUNCTION, "fre(<anything>)",
       "How many bytes are free for the program's variables and strings. Above 32767 it comes out "
       "negative: fre(0) - (fre(0) < 0) * 65536 gives the true figure.",
       "10 print fre(0) - (fre(0) < 0) * 65536", "fR"),
    _k("get", STATEMENT, "get <variable> [, ...]    get# <file number>, <variable>",
       "Takes one key from the keyboard without waiting: an empty string (or 0) when none has been "
       "pressed, so it's usually in a loop. Only in a program, not typed directly. get# reads one "
       "character from an open file.",
       "10 get k$: if k$ = \"\" then 10", "gE"),
    _k("go", PART, "go to <line>", "Go and to may be written apart: go to 100 is goto 100.",
       "10 go to 100", ""),
    _k("gosub", STATEMENT, "gosub <line>",
       "Runs the subroutine at that line, which ends with return; the program then carries on after "
       "the gosub.",
       "10 gosub 1000\n...\n1000 print \"subroutine\": return", "goS"),
    _k("goto", STATEMENT, "goto <line>", "Carries on from that line.", "20 goto 10", "gO"),
    _k("if", STATEMENT, "if <condition> then <line or statements>    if <condition> goto <line>",
       "When the condition is true (not zero), goes to the line or runs the statements after then. "
       "When it's false, the rest of the line is skipped.",
       "10 if s > hs then hs = s: print \"new high score\"", ""),
    _k("input", STATEMENT, "input [\"<prompt>\";] <variable> [, <variable> ...]",
       "Asks for something to be typed (showing a question mark) and puts it in the variables. "
       "Typing letters for a number gives ?REDO FROM START. Only in a program, not typed directly.",
       "10 input \"your name\"; n$", ""),
    _k("input#", STATEMENT, "input# <file number>, <variable> [, ...]",
       "Reads values from an open file, as input reads them from the keyboard: up to a comma or "
       "Return.",
       "10 open 2,8,2,\"scores,s,r\": input#2, s: close 2", "iN"),
    _k("int", FUNCTION, "int(<number>)",
       "The whole number at or below it: int(3.7) is 3, int(-3.2) is -4.",
       "10 d = int(rnd(1) * 6) + 1", ""),
    _k("left$", FUNCTION, "left$(<string>, <length>)", "The first characters of the string.",
       "10 print left$(\"commodore\", 4): rem comm", "leF"),
    _k("len", FUNCTION, "len(<string>)", "How many characters the string has (0 to 255).",
       "10 print len(n$)", ""),
    _k("let", STATEMENT, "[let] <variable> = <value>",
       "Gives a variable a value. Let may be left out: x = 5 is the same.", "10 let x = 5", "lE"),
    _k("list", STATEMENT, "list [<first>] [-] [<last>]",
       "Lists the program, or the lines asked for: list 100-200, list -50, list 300-.",
       "list 100-200", "lI"),
    _k("load", STATEMENT, "load [\"<name>\" [, <device> [, <secondary>]]]",
       "Loads a program, from tape (device 1, the default) or disk (8). With secondary address 1 it "
       "goes where it was saved from, as machine code needs. In a running program it loads and "
       "starts the program again from its first line, keeping the variables.",
       "load \"game\",8,1", "lO"),
    _k("log", FUNCTION, "log(<number>)",
       "The natural logarithm (base e). A number of 0 or below gives ?ILLEGAL QUANTITY ERROR. "
       "log(x) / log(10) is the base-10 logarithm.", "10 print log(100) / log(10)", ""),
    _k("mid$", FUNCTION, "mid$(<string>, <start> [, <length>])",
       "Part of the string, from character <start> (the first is 1), to the end or <length> long.",
       "10 print mid$(\"commodore\", 4, 3): rem mod", "mI"),
    _k("new", STATEMENT, "new", "Wipes the program and its variables from memory.", "new", ""),
    _k("next", STATEMENT, "next [<variable> [, <variable> ...]]",
       "Ends a for loop: adds the step and goes back to the for while the end hasn't been passed. "
       "next j, i ends two loops at once.",
       "10 for i = 1 to 3: print i: next i", "nE"),
    _k("not", OPERATOR, "not <value>",
       "True when the value is false. On numbers it flips every bit of a 16-bit whole number: not 0 "
       "is -1 (true), not -1 is 0.",
       "10 if not f then print \"not found\"", "nO"),
    _k("on", STATEMENT, "on <number> goto <line>, <line>, ...    on <number> gosub <line>, ...",
       "Goes to the first line for 1, the second for 2, and so on. When the number is 0 or more than "
       "there are lines, it carries on after the on.",
       "10 on d goto 100, 200, 300", ""),
    _k("open", STATEMENT, "open <file number> [, <device> [, <secondary> [, \"<name>\"]]]",
       "Opens a file or device for print#, input#, get# and cmd. The file number is your choice "
       "(1-255); the device is 1 tape, 3 screen, 4 printer, 8 disk. Opening device 8 with secondary "
       "address 15 talks to the drive itself.",
       "10 open 2,8,2,\"scores,s,w\"\n20 open 15,8,15,\"i0\"", "oP"),
    _k("or", OPERATOR, "<a> or <b>",
       "In a condition, true when either side is. On numbers it works bit by bit on 16-bit whole "
       "numbers, so it also sets bits: peek(53265) or 16.",
       "10 if k$ = \"q\" or k$ = \"Q\" then end", ""),
    _k("peek", FUNCTION, "peek(<address>)", "The byte (0-255) in memory at the address (0-65535).",
       "10 print peek(53280) and 15: rem the border colour", "pE"),
    _k("poke", STATEMENT, "poke <address>, <value>",
       "Puts a byte (0-255) into memory at the address (0-65535): the way BASIC sets the screen, "
       "colours, sprites and sound.",
       "10 poke 53280, 0: poke 53281, 0: rem black border and background", "pO"),
    _k("pos", FUNCTION, "pos(<anything>)", "The cursor's column on its line (0-79 on a long line).",
       "10 if pos(0) > 30 then print", ""),
    _k("print", STATEMENT, "print [<things to print>]    ? [...]",
       "Prints numbers and strings. A semicolon between them prints them together; a comma moves to "
       "the next 10-column zone. Ending with ; or , keeps the cursor on the line. ? is short for "
       "print. Numbers print with a space before them (or a minus sign) and after.",
       "10 print \"score\"; s, \"lives\"; l", "?"),
    _k("print#", STATEMENT, "print# <file number>, <things to print>",
       "Prints to an open file instead of the screen. Separate values written for input# to read "
       "back with chr$(13) (Return).",
       "10 print#2, s; chr$(13); n$", "pR"),
    _k("read", STATEMENT, "read <variable> [, <variable> ...]",
       "Takes the next values from the program's data lines. Running out gives ?OUT OF DATA ERROR; "
       "restore starts them again.",
       "10 for i = 0 to 62: read b: poke 832 + i, b: next", "rE"),
    _k("rem", STATEMENT, "rem <anything>", "A remark: the rest of the line is ignored.",
       "10 rem *** set up the screen ***", ""),
    _k("restore", STATEMENT, "restore",
       "Makes read start again from the first data in the program.", "100 restore", "reS"),
    _k("return", STATEMENT, "return",
       "Ends a subroutine: carries on after the gosub that called it. Without one, ?RETURN WITHOUT "
       "GOSUB ERROR.", "1090 return", "reT"),
    _k("right$", FUNCTION, "right$(<string>, <length>)", "The last characters of the string.",
       "10 print right$(\"00000\" + mid$(str$(s), 2), 5): rem s with leading zeros", "rI"),
    _k("rnd", FUNCTION, "rnd(<number>)",
       "A random number from 0 up to (not including) 1. A positive number gives the next in the "
       "sequence; a negative one starts the sequence from that number (the same each time); 0 takes "
       "one from the machine's clock. int(rnd(1) * n) gives 0 to n - 1.",
       "10 x = rnd(-ti): rem a different sequence each run\n20 d = int(rnd(1) * 6) + 1", "rN"),
    _k("run", STATEMENT, "run [<line>]",
       "Clears the variables and starts the program, from its first line or the one given.",
       "run", "rU"),
    _k("save", STATEMENT, "save [\"<name>\" [, <device> [, <secondary>]]]",
       "Saves the program, to tape (device 1, the default) or disk (8). On disk, a name starting @0: "
       "replaces a file already there.",
       "save \"game\",8", "sA"),
    _k("sgn", FUNCTION, "sgn(<number>)", "1 for a positive number, -1 for a negative one, 0 for 0.",
       "10 dx = sgn(tx - x)", "sG"),
    _k("sin", FUNCTION, "sin(<angle>)", "The sine of an angle in radians.",
       "10 y = 100 + 50 * sin(a)", "sI"),
    _k("spc(", FUNCTION, "spc(<count>)", "In print: moves the cursor that many places on.",
       "10 print spc(10); \"indented\"", "sP"),
    _k("sqr", FUNCTION, "sqr(<number>)", "The square root. Negative numbers give ?ILLEGAL QUANTITY ERROR.",
       "10 d = sqr(dx * dx + dy * dy)", "sQ"),
    _k("step", PART, "for ... to ... step <amount>",
       "How much a for loop adds each time (1 if left out). It may be negative or a fraction.",
       "10 for i = 10 to 1 step -1: print i: next", "stE"),
    _k("stop", STATEMENT, "stop",
       "Stops the program with BREAK IN <line>. Cont carries on from there; handy for looking at "
       "variables while testing.", "100 stop", "sT"),
    _k("str$", FUNCTION, "str$(<number>)",
       "The number as a string, as print would show it: with a leading space for a positive number.",
       "10 s$ = mid$(str$(s), 2): rem without the space", "stR"),
    _k("sys", STATEMENT, "sys <address>",
       "Runs machine code at the address, which ends with rts to come back to BASIC. A, X, Y and the "
       "status register are set from 780-783 beforehand, and saved there afterwards.",
       "10 sys 49152", "sY"),
    _k("tab(", FUNCTION, "tab(<column>)",
       "In print: moves the cursor on to that column (0-based) of the line, if it isn't past it.",
       "10 print \"name\"; tab(20); \"score\"", "tA"),
    _k("tan", FUNCTION, "tan(<angle>)", "The tangent of an angle in radians.", "10 h = d * tan(a)", ""),
    _k("then", PART, "if <condition> then <line or statements>",
       "Follows the condition in an if: a line number to go to, or statements to run.",
       "10 if x = 1 then 100", "tH"),
    _k("to", PART, "for <variable> = <start> to <end>", "The end value of a for loop.",
       "10 for i = 1 to 10", ""),
    _k("usr", FUNCTION, "usr(<number>)",
       "Calls machine code whose address is at 785-786 (low byte first), with the number in the "
       "floating-point accumulator; what's left there is the result.",
       "10 poke 785, 0: poke 786, 192: x = usr(5)", "uS"),
    _k("val", FUNCTION, "val(<string>)",
       "The number at the start of a string: val(\"12ab\") is 12, val(\"abc\") is 0.",
       "10 input \"level\"; l$: l = val(l$)", "vA"),
    _k("verify", STATEMENT, "verify [\"<name>\" [, <device> [, <secondary>]]]",
       "Compares a saved program with the one in memory: OK, or ?VERIFY ERROR.",
       "verify \"game\",8", "vE"),
    _k("wait", STATEMENT, "wait <address>, <mask> [, <flip>]",
       "Waits until (peek(address) xor flip) and mask isn't 0. The RUN/STOP key doesn't stop it.",
       "10 wait 198, 255: rem until a key is in the keyboard buffer", "wA"),
]}

# What else a word in BASIC can be that's worth a note: the variables the ROM keeps itself
SPECIAL = {
    "ti": Keyword("ti", "variable", "ti",
                  "The jiffy clock: sixtieths of a second since the machine was switched on (or ti$ "
                  "was set). It can't be given a value.", "10 t = ti: rem time a loop with ti - t"),
    "ti$": Keyword("ti$", "variable", "ti$",
                   "The clock as a six-digit string, hhmmss. Setting it (ti$ = \"000000\") sets the time.",
                   "10 ti$ = \"000000\"\n20 print ti$"),
    "st": Keyword("st", "variable", "st",
                  "The status of the last input or output to a file or device: 0 when all went well, "
                  "64 at the end of a file.", "50 get#2, a$: if st = 0 then 50"),
}

_LINE_NUMBER = re.compile(r"^\s*\d+")
_SPECIAL = re.compile(r"(ti\$|ti|st)(?![a-z0-9$])", re.I)


def lookup(word: str) -> Keyword | None:
    """The help for a keyword (any case; tab and tab( alike), or ti, ti$ or st."""
    w = word.strip().lower()
    if w in KEYWORDS:
        return KEYWORDS[w]
    if w + "(" in KEYWORDS:
        return KEYWORDS[w + "("]
    if w == "?":
        return KEYWORDS["print"]
    if w == "get#":
        return KEYWORDS["get"]
    return SPECIAL.get(w)


def keyword_at(line: str, col: int) -> Keyword | None:
    """The keyword at column ``col`` of a line of BASIC (listing notation), found as the C64 crunches
    the line: not in strings, after rem, or in data. None if there isn't one (or it's an operator
    such as +, which has no help). The line number may be there or not (pBASIC)."""
    m = _LINE_NUMBER.match(line)
    base = m.end() if m else 0
    text = line[base:]
    c = col - base
    if c < 0:
        return None
    try:
        src = _source_bytes(text, 0)
    except Exception:           # a {code} it doesn't know: no help
        return None
    in_quote = in_data = False
    i, n = 0, len(src)
    while i < n:
        b, literal = src[i][0], src[i][1]
        start = src[i][3]
        if b == 0x22:
            in_quote = not in_quote
            i += 1
            continue
        if in_quote or literal or b == 0x20:
            i += 1
            continue
        if in_data:
            in_data = b != 0x3A
            i += 1
            continue
        if b == 0x3F:                                # ?
            if start <= c < src[i][4]:
                return KEYWORDS["print"]
            i += 1
            continue
        if 0x30 <= b <= 0x3B:
            i += 1
            continue
        found = match_keyword(src, i, None)
        if found:
            _tok, k, name = found
            end = src[i + k - 1][4]
            if start <= c < end:
                return lookup(name)
            i += k
            if name == "data":
                in_data = True
            elif name == "rem":
                return None                           # the rest is a remark
            continue
        # not a keyword: the start of a variable name? (ti, ti$ and st are worth a note)
        prev = text[start - 1] if start > 0 else " "
        if not prev.isalnum():
            m = _SPECIAL.match(text, start)
            if m and start <= c < m.end():
                return SPECIAL[m.group(1).lower()]
        i += 1
    return None


def describe(k: Keyword) -> str:
    """The help as plain text (a tooltip, or a page)."""
    out = [f"{k.title}  ({k.kind})", k.form, "", k.text]
    if k.example:
        out += ["", "Example:", k.example]
    if k.abbrev:
        out += ["", f"Abbreviation: {k.abbrev}"]
    return "\n".join(out)
