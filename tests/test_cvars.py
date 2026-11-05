from l64s.cvars import CType, format_value, frame_base, local_address, parse_source

SRC = r'''
#include <conio.h>
#define MAX 10   /* a comment with int fake; in it */
typedef unsigned char byte;
struct point { int x; int y; };
unsigned char flag;
static int counter = 5, other;
char name[10] = "hi; there";
long big;
struct point pos;
int *ptr;
byte table[MAX];
uint16_t word;
enum colour { RED, GREEN } col;
int twice(int x);
static void helper(unsigned char a, char *s) { a = *s; }
int main(void) {
    int i;
    unsigned char c = 3;
    static int calls;
    register int r = 7;
    struct point here;
    for (i = 0; i < 3; ++i) { int inner = i; counter += inner; }
    ++calls;
    return 0;
}
'''


def test_globals():
    g = parse_source(SRC).globals
    assert str(g["flag"]) == "unsigned char" and str(g["counter"]) == "int" and str(g["other"]) == "int"
    assert str(g["name"]) == "char[10]" and str(g["big"]) == "long" and str(g["pos"]) == "struct point"
    assert str(g["ptr"]) == "int *" and str(g["table"]) == "unsigned char[10]"      # MAX is #defined as 10
    assert str(g["word"]) == "unsigned int" and str(g["col"]) == "enum colour"
    assert "twice" not in g and "main" not in g and "fake" not in g


def test_functions_params_and_locals():
    src = parse_source(SRC)
    main = src.functions["main"]
    assert (main.first_line, main.last_line) == (17, 26) and main.params == []
    assert [(n, str(t), ln, end) for n, t, ln, end in main.locals] == [
        ("i", "int", 18, 26), ("c", "unsigned char", 19, 26), ("r", "int", 21, 26),
        ("here", "struct point", 22, 26), ("inner", "int", 23, 23)]   # (static calls isn't on the stack)
    assert [(n, str(t)) for n, t in src.functions["helper"].params] == [("a", "unsigned char"), ("s", "char *")]


def test_sizes():
    src = parse_source(SRC)
    g = src.globals
    assert g["flag"].size() == 1 and g["counter"].size() == 2 and g["big"].size() == 4 and g["ptr"].size() == 2
    assert g["name"].size() == 10 and g["pos"].size(src.structs) == 4 and g["table"].size() == 10


def test_format():
    structs = parse_source(SRC).structs
    assert format_value(CType("int"), b"\xff\xff") == "-1 ($FFFF)"
    assert format_value(CType("int", True), b"\xff\xff") == "65535 ($FFFF)"
    assert format_value(CType("char", True), b"\x41") == "65 ($41, 'a')"
    assert format_value(CType("long"), b"\x01\x00\x01\x00") == "65537 ($00010001)"
    assert format_value(CType("int", pointer=1), b"\x00\x04") == "$0400"
    assert format_value(CType("char", pointer=1), b"\x00\x00") == "NULL"
    assert format_value(CType("char", dims=(10,)), b"HELLO\x00xx\x00\x00") == '"hello"'
    assert format_value(CType("int", dims=(3,)), b"\x01\x00\x02\x00\x03\x00") == "{1 ($0001), 2 ($0002), 3 ($0003)}"
    assert format_value(CType("struct", tag="point"), b"\x05\x00\xfe\xff", structs) == \
        "{x = 5 ($0005), y = -2 ($FFFE)}"
    assert format_value(CType("struct", tag="nope"), b"\x01\x02") == "01 02"


def test_frame_base_counts_only_locals_declared_before_the_line():
    src = parse_source("int twice(int x) {\n    int y = x * 2;\n    return y;\n}\n")
    fn = src.functions["twice"]
    offsets = {"x": 0, "y": -2}
    # measured in VICE: at the start of line 2, sp = $CFF5 and x is there; on line 3, y is pushed (sp $CFF3)
    assert frame_base(0xCFF5, fn, 2, offsets) == 0xCFF5
    assert frame_base(0xCFF3, fn, 3, offsets) == 0xCFF5
    assert local_address(0xCFF5, offsets["y"]) == 0xCFF3 and local_address(0xCFF5, None) == 0xCFF5
    main = parse_source(SRC).functions["main"]
    # main at line 24 (++calls): i, c and r are on the stack (offsets -2, -3, -5) and sp = $CFF7
    assert frame_base(0xCFF7, main, 24, {"i": -2, "c": -3, "r": -5}) == 0xCFFC


def test_a_block_s_locals_are_freed_at_its_end():
    src = parse_source("void f(void) {\n    int a = 1;\n    {\n        int b = 2;\n        a = b;\n    }\n"
                       "    a = 3;\n}\n")
    fn = src.functions["f"]
    offs = {"a": -2, "b": -4}
    assert frame_base(0x100, fn, 5, offs) == 0x104      # in the block: a and b
    assert frame_base(0x100, fn, 7, offs) == 0x102      # after it: only a


def test_program_variables_at_a_stop():
    from l64s.cvars import CProgram
    main_c = "int n;\nint twice(int x);\nint main(void) {\n    int i;\n    unsigned char c = 3;\n" \
             "    for (i = 0; i < 3; ++i) { n += twice(i) + c; }\n    return 0;\n}\n"
    util_c = "int twice(int x) {\n    int y = x * 2;\n    return y;\n}\n"
    prog = CProgram({"/p/main.c": main_c, "/p/util.c": util_c}, {"n": (0x9F0, 2), "seen": (0x9F2, 3)},
                    {"main": {"i": -2, "c": -3}, "twice": {"x": None, "y": -2}})
    fn, vs = prog.variables(("/p/main.c", 6), 0xCFF7)
    assert fn.name == "main"
    assert [(v.group, v.name, v.type_name, v.address, v.size, v.note) for v in vs] == [
        ("local", "i", "int", 0xCFF8, 2, ""), ("local", "c", "unsigned char", 0xCFF7, 1, ""),
        ("global", "n", "int", 0x9F0, 2, ""), ("global", "seen", "?", 0x9F2, 3, "")]
    fn, vs = prog.variables(("/p/main.c", 5), 0xCFF8)          # on c's declaration: not there yet
    assert [(v.name, v.address, v.note) for v in vs[:2]] == [("i", 0xCFF8, ""), ("c", None, "not declared yet")]
    fn, vs = prog.variables(("/p/util.c", 1), 0xCFF5)          # first line: the argument isn't in place
    assert fn.name == "twice" and vs[0].note == "set up as the function starts"
    fn, vs = prog.variables(("/p/util.c", 3), 0xCFF3)
    assert [(v.name, v.address) for v in vs[:2]] == [("x", 0xCFF5), ("y", 0xCFF3)]
    assert prog.show(vs[0], b"\x2a\x00") == "42 ($002A)" and prog.show(vs[-1], b"\x01\x02\x03") == "01 02 03"
    assert prog.variables(None, 0)[0] is None                    # not in C: globals only


def test_macro_sizes_and_constant_expressions():
    from l64s.cvars import constant
    macros = {"W": "40", "H": "25", "SCREEN": "(W * H)", "BIG": "0x100UL", "ODD": "foo(3)"}
    assert constant("W * H", macros) == 1000 and constant("SCREEN + 1", macros) == 1001
    assert constant("BIG", macros) == 256 and constant("ODD", macros) == 0 and constant("", macros) == 0
    assert constant("__import__('os')", macros) == 0
    src = parse_source("#include \"x.h\"\nchar screen[SCREEN];\nint rows[H][2];\n", macros)
    assert src.globals["screen"].size() == 1000 and src.globals["rows"].size() == 100


def test_two_files_with_the_same_function_name():
    from l64s.cvars import CProgram
    a = "int main(void) {\n    int x = 1;\n    return x;\n}\n"
    b = "void main(void) {\n    char c;\n    c = 2;\n}\n"
    prog = CProgram({"/a.c": a, "/b.c": b}, {}, {"main": {"c": -1}})
    assert prog.function_at("/b.c", 3).locals[0][0] == "c" and prog.function_at("/a.c", 3).locals[0][0] == "x"
