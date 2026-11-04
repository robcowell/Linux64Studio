"""The task list: TODOs in the project's sources."""
from l64s.asm.assembler import Assembler, Options
from l64s.tasks import Task, TaskList, basic_todo, scan, todo_line

ASM = """*=$c000
        todo add bounds checking to the array
TODO: don't forget the hi-score
start   lda #0          ; TODO speed this up
        sta $d020       // FIXME: the wrong colour
        jmp start       ; a todo in lower case
        byte "todo"     ; not a task: it's in a string
/* HACK: until the
   loader works */  rts
        text 'say ;todo'
"""


def test_scan_assembler():
    assert [(t.line, t.kind, t.text) for t in scan(ASM)] == [
        (2, "TODO", "add bounds checking to the array"),
        (3, "TODO", "don't forget the hi-score"),
        (4, "TODO", "speed this up"),
        (5, "FIXME", "the wrong colour"),
        (6, "TODO", "in lower case"),
        (8, "HACK", "until the")]


def test_the_assembler_skips_todo():
    r = Assembler(Options()).assemble_text(ASM)
    assert r.ok, [str(d) for d in r.diagnostics]
    assert bytes(r.memory[0xC000:0xC003]) == bytes([0xA9, 0, 0x8D])
    r = Assembler(Options()).assemble_text("*=$c000\ntodoist rts\n        jmp todoist\n")
    assert r.ok and r.symbols["todoist"] == 0xC000                 # only the word todo


def test_scan_basic():
    src = '10 rem todo speed this up\n20 print "rem todo": rem fixme: wrong\n30 print "todo"\n'
    assert [(t.line, t.kind, t.text) for t in scan(src, basic=True)] == [(1, "TODO", "speed this up"),
                                                                       (2, "FIXME", "wrong")]


def test_task_list(tmp_path):
    a, b = tmp_path / "a.asm", tmp_path / "b.bas"
    a.write_text("        todo one\n")
    b.write_text("10 rem todo two\n")
    tl = TaskList()
    got = tl.update([a, b])
    assert [(t.text, t.line) for t in got] == [("one", 1), ("two", 1)]
    assert tl.update([a, b], {str(a): "\n\n; TODO moved\n"})[0] == Task(str(a.resolve()), 3, "TODO", "moved")
    a.write_text("rts\n")
    assert [t.text for t in tl.update([a, b])] == ["two"]
    assert [t.text for t in tl.update([b])] == ["two"]


def test_add_todo_lines():
    assert todo_line("        lda #0", "check it", "cbm") == "        todo check it"
    assert todo_line("\tlda #0", "check it", "kick") == "\t// TODO check it"
    assert todo_line("print 1", "x", "pbasic") == "rem todo x"
    text, line = basic_todo("10 print\n20 goto 10\n", 2, "fix")
    assert text == "10 print\n15 rem todo fix\n20 goto 10\n" and line == 2
    text, line = basic_todo("10 print\n11 goto 10\n", 2, "fix")
    assert text == "10 print\n11 goto 10: rem todo fix\n" and line == 2
    assert basic_todo("10 print\n", 1, "a")[0] == "9 rem todo a\n10 print\n"
    assert basic_todo("0 print\n", 1, "a")[0] == "0 print: rem todo a\n"
