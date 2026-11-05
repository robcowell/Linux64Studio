"""The main window's menu bar, laid out like CBM prg Studio's: File, Edit, Project, Build, Debugger,
Tools, Git, Window and Help. Keyboard shortcuts set on the application show beside their items.
"""
from __future__ import annotations

from gi.repository import Gio, GLib

# Edit's items forward to the focused text widget's own actions (see MainWindow._edit); their keys are
# the widget's own, so they're shown here rather than set as application accelerators.
EDIT_ITEMS = (("_Undo", "text.undo", "<Control>z"), ("_Redo", "text.redo", "<Control><Shift>z"),
              None,
              ("Cu_t", "clipboard.cut", "<Control>x"), ("_Copy", "clipboard.copy", "<Control>c"),
              ("_Paste", "clipboard.paste", "<Control>v"), ("_Delete", "selection.delete", None),
              None,
              ("Select _All", "selection.select-all", "<Control>a"))


def _menu(*sections) -> Gio.Menu:
    """A menu from sections, each a list of (label, action) pairs or (label, submenu) pairs."""
    menu = Gio.Menu()
    for items in sections:
        sec = Gio.Menu()
        for label, what in items:
            if isinstance(what, Gio.MenuModel):
                sec.append_submenu(label, what)
            elif isinstance(what, Gio.MenuItem):
                sec.append_item(what)
            else:
                sec.append(label, what)
        menu.append_section(None, sec)
    return menu


def _edit_menu() -> Gio.Menu:
    sections, cur = [], []
    for it in EDIT_ITEMS:
        if it is None:
            sections.append(cur)
            cur = []
            continue
        label, action, accel = it
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value("win.edit", GLib.Variant.new_string(action))
        if accel:
            item.set_attribute_value("accel", GLib.Variant.new_string(accel))
        cur.append((label, item))
    sections.append(cur)
    sections.append([("_Go to Line…", "win.goto-line"), ("Go to _Definition", "win.goto-definition"),
                     ("Go _Back", "win.go-back")])
    sections.append([("Add _TODO…", "win.add-todo")])
    return _menu(*sections)


def new_menu() -> Gio.Menu:
    """File → New, and the toolbar's New button."""
    return _menu([("_Project…", "win.new-project")],
                 [("_Source File…", "win.new-file::asm"), ("_BASIC File…", "win.new-file::bas"),
                  ("p_BASIC File (no line numbers)…", "win.new-file::pbas")],
                 [("Sp_rite Set…", "win.new-file::spt"), ("_Character Set…", "win.new-file::cst"),
                  ("Screen _Design…", "win.new-file::sdd"), ("Dis_k Image…", "win.new-file::d64")])


def build_menubar(recent: Gio.MenuModel, user_tools: Gio.MenuModel) -> Gio.Menu:
    new = new_menu()
    file = _menu([("_New", new), ("_Open Project…", "win.open-project"), ("Open _File…", "win.open-file"),
                  ("Open _Recent", recent)],
                 [("_Save", "win.save"), ("Save A_ll", "win.save-all")],
                 [("_Close Tab", "win.close-tab"), ("Close Pro_ject", "win.close-project")],
                 [("_Print…", "win.print"), ("Print Pre_view…", "win.print-preview")],
                 [("_Quit", "app.quit")])
    project = _menu([("_New Project…", "win.new-project"), ("_Open Project…", "win.open-project")],
                    [("_Properties…", "win.project-properties")],
                    [("_Close Project", "win.close-project")])
    build = _menu([("Build _Project", "win.build-project"), ("Build Current _File", "win.build-file")],
                  [("Build Project and _Run", "win.run-project"),
                   ("Build Current File and R_un", "win.run-file")])
    debugger = _menu([("_Debug Project", "win.debug-project")],
                     [("_Continue", "win.debug-continue"), ("Step _Over", "win.debug-over"),
                      ("Step _Into", "win.debug-into"), ("Step O_ut", "win.debug-out")],
                     [("Toggle _Breakpoint", "win.toggle-breakpoint")],
                     [("_Memory Viewer", "win.memory-viewer"), ("_Snapshots", "win.snapshots")])
    basic = _menu([("_List BASIC Program (.prg)…", "win.list-prg"), ("_Renumber…", "win.renumber"),
                   ("Re_format…", "win.reformat-basic"), ("_Statistics", "win.basic-statistics")],
                  [("_Compress (abbreviate keywords)", "win.basic-compress"),
                   ("_Uncompress (keywords in full)", "win.basic-uncompress")],
                  [("Convert to _pBASIC", "win.convert-to-pbasic"),
                   ("Preview _Generated BASIC (pBASIC)", "win.pbasic-preview")],
                  [("Create _Token File…", "win.create-token-file")])
    music = _menu([("_SID Designer", "win.sid-designer")],
                  [("Compose in Sid_Monkey", "win.music-app::sidmonkey"),
                   ("Open _GoatTracker", "win.music-app::goattrk2")])
    tools = _menu([("_BASIC", basic), ("_Music", music)],
                  [("Screen _Code Builder", "win.screen-codes"), ("Screen C_alculator", "win.screen-calculator"),
                   ("Code S_nippets", "win.snippets"), ("S_YS() Call Generator", "win.sys-call"),
                   ("_Data Generator", "win.data-generator"), ("St_ring Formatter", "win.string-formatter")],
                  [("Source A_nalyser", "win.source-analyser"), ("_UTF-8 Check", "win.utf8-check"),
                   ("Con_vert Source (Develop 64, Genesis, TASM)…", "win.convert-source")],
                  [("_Import CharPad Binaries…", "win.import-charpad"),
                   ("Binary _Import/Export", "win.binary-tool"), ("Di_sassembler", "win.disassembler"),
                   ("Memory Mana_ger", "win.memory-manager")],
                  [("User _Tools", user_tools)],
                  [("_Preferences", "app.preferences")])
    git = _menu([("_Status", "win.git-status"), ("_Changes (diff)", "win.git-diff"), ("_History (log)", "win.git-log")],
                [("C_ommit…", "win.git-commit"), ("_Add All Files", "win.git-add-all"),
                 ("Manage _Ignore List", "win.git-ignore")],
                [("Create a _Repository for the Project", "win.git-init")])
    window = _menu([("Project _Information", "win.project-info")],
                   [("_Close Tab", "win.close-tab"), ("Close _All Tabs", "win.tab-close-all")])
    help_ = _menu([("_Keyboard Shortcuts", "app.shortcuts")], [("_About Linux64Studio", "app.about")])

    bar = Gio.Menu()
    for label, m in (("_File", file), ("_Edit", _edit_menu()), ("_Project", project), ("_Build", build),
                     ("_Debugger", debugger), ("_Tools", tools), ("_Git", git), ("_Window", window),
                     ("_Help", help_)):
        bar.append_submenu(label, m)
    return bar
