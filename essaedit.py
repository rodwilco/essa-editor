#!/usr/bin/env python3
"""
Essa Editor — a terminal Markdown word processor.

Features:
  * Inline WYSIWYG rendering: **bold**, *italic*, <u>underline</u> (and ++underline++),
    ~~strikethrough~~, `code`, headers, lists, blockquotes, links — styled live as you type.
    Markers are dimmed; content carries the real attribute.
  * Spell check (pyspellchecker) with red-underlined misspellings, suggestion popup (F7),
    jump-to-next (F8), and a personal dictionary (~/.config/essaedit/dictionary.txt).
  * Mouse support toggleable at runtime (F2). Mouse OFF restores native terminal
    selection/copy; mouse ON gives click-to-place-cursor, drag-select, scroll wheel.
  * 256-color theme, line numbers, soft wrap (F6), incremental search (Ctrl+F),
    undo (Ctrl+Z), cut/copy/paste (Ctrl+X/C/V).

Dependencies: prompt_toolkit >= 3.0, pyspellchecker >= 0.8
Run: python3 essaedit.py [file.md] [--no-mouse] [--no-spell]

Copyright (C) 2026 Colin Lewis
SPDX-License-Identifier: GPL-3.0-or-later

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details. You should have received
a copy of the GNU General Public License along with this program.
If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.clipboard import InMemoryClipboard
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.margins import NumberedMargin, ScrollbarMargin
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.search import start_search
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, SearchToolbar, TextArea

from spellchecker import SpellChecker

# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")

HEADER_RE = re.compile(r"^(#{1,6})\s")
QUOTE_RE = re.compile(r"^\s*>")
HR_RE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")
BULLET_RE = re.compile(r"^(\s*)([-*+]|\d{1,3}\.)(\s+)(\[(?: |x|X)\]\s+)?")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<bolditalic>\*\*\*(?!\s)(?:[^*\n]|\*(?!\*\*))+?(?<!\s)\*\*\*)"
    r"|(?P<bold>\*\*(?!\s)(?:[^*\n]|\*(?!\*))+?(?<!\s)\*\*)"
    r"|(?P<bold2>(?<![A-Za-z0-9_])__(?!\s)[^_\n]+?(?<!\s)__(?![A-Za-z0-9_]))"
    r"|(?P<italic>(?<![*\w])\*(?![\s*])[^*\n]+?(?<!\s)\*(?!\*))"
    r"|(?P<italic2>(?<![A-Za-z0-9_])_(?![\s_])[^_\n]+?(?<!\s)_(?![A-Za-z0-9_]))"
    r"|(?P<strike>~~(?!\s)[^~\n]+?(?<!\s)~~)"
    r"|(?P<underline><u>.*?</u>|\+\+(?!\s)[^+\n]+?(?<!\s)\+\+)"
    r"|\[(?P<linktext>[^\]\n]*)\]\((?P<linkhref>[^)\n]*)\)"
    r"|(?P<url>https?://[^\s<>()\[\]]+)"
)

# --------------------------------------------------------------------------
# Style / theme
# --------------------------------------------------------------------------

STYLE = Style.from_dict(
    {
        # Markdown elements
        "h1": "bold #5fffff",
        "h2": "bold #5fd7ff",
        "h3": "bold #5fafff",
        "h4": "bold #5f87ff",
        "h5": "bold #875fff",
        "h6": "bold #af5fff",
        "bold": "bold",
        "italic": "italic",
        "bolditalic": "bold italic",
        "underline": "underline",
        "strike": "strike #808080",
        "code": "#ffd75f",
        "codeblock": "#d7af5f",
        "marker": "#5f5f5f",
        "quote": "italic #87d787",
        "bullet": "bold #ff87d7",
        "hr": "#5f5f5f",
        "link": "underline #5fafff",
        "linkurl": "#5f5f87",
        "misspelled": "underline #ff5f5f",
        # Chrome
        "line-number": "#585858",
        "line-number.current": "bold #afaf00",
        "cursor-line": "bg:#262626",
        "status": "reverse",
        "status.mod": "bold reverse fg:#ffaf00",
        "status.msg": "reverse fg:#5fff87",
        "status.off": "reverse fg:#808080",
        "minibar": "bg:#303030 #ffffff",
        "minibar.label": "bg:#303030 bold #ffd700",
        "menu": "bg:#262626 #d0d0d0",
        "menu.selected": "bg:#005f87 bold #ffffff",
        "menu.title": "bg:#262626 bold #ffd700",
        "frame.border": "#5f5f5f",
        "frame.label": "bold #ffd700",
        "search-toolbar": "bg:#303030 #ffffff",
    }
)

HELP_TEXT = """\
 FILE
   Ctrl+S   Save (prompts for a name if the buffer is new)
   Ctrl+O   Open file
   Ctrl+N   New buffer
   Ctrl+Q   Quit (asks about unsaved changes)

 FORMATTING (works on selection, or inserts markers at cursor)
   Ctrl+B   Bold        **text**
   Alt+I    Italic      *text*        (Ctrl+I is Tab in terminals)
   Ctrl+U   Underline   <u>text</u>   (++text++ also renders)

 EDITING
   Ctrl+Z   Undo
   Ctrl+X / Ctrl+C / Ctrl+V   Cut / Copy / Paste
   Ctrl+F   Search (Enter = next, Esc = cancel)
   Tab      Insert 4 spaces
   Shift+Arrows   Select text (terminal permitting)

 SPELLING
   F7       Suggestions for word under cursor ('a' adds to dictionary)
   F8       Jump to next misspelled word
   F3       Toggle spell check on/off

 VIEW / INPUT
   F1       This help (Esc or q to close)
   F2       Toggle mouse capture.  ON: click to move cursor, drag to
            select, wheel to scroll.  OFF: the terminal's native mouse
            selection and copy/paste work as usual.
   F6       Toggle soft line wrap

 Personal dictionary: ~/.config/essaedit/dictionary.txt
 Formatting markers must open and close on the same line to render.
"""

DICT_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "essaedit" / "dictionary.txt"


def make_clipboard():
    """Use the system clipboard via pyperclip when a backend exists, else in-memory."""
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(pyperclip.paste())  # probe for a working backend
        from prompt_toolkit.clipboard.pyperclip import PyperclipClipboard

        return PyperclipClipboard()
    except Exception:
        return InMemoryClipboard()


# --------------------------------------------------------------------------
# Lexer: markdown inline styling + spell-check overlay
# --------------------------------------------------------------------------

class MarkdownSpellLexer(Lexer):
    def __init__(self, editor: "Editor"):
        self.editor = editor
        self._cache: dict = {}

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _fence_flags(lines):
        """For each line: True if it is inside (or delimits) a fenced code block."""
        flags = []
        in_fence = False
        for ln in lines:
            if FENCE_RE.match(ln):
                flags.append(True)
                in_fence = not in_fence
            else:
                flags.append(in_fence)
        return flags

    @staticmethod
    def _merge(styles, line):
        """Collapse a per-character style list into (style, text) fragments."""
        frags = []
        start = 0
        cur = styles[0]
        for i in range(1, len(line)):
            if styles[i] != cur:
                frags.append((cur, line[start:i]))
                start, cur = i, styles[i]
        frags.append((cur, line[start:]))
        return frags

    def _spell_eligible(self, word: str) -> bool:
        return len(word) >= 2 and not word.isupper()

    # -- main per-line lexing -------------------------------------------------

    def _lex_line(self, line: str, in_fence: bool, spell_on: bool):
        n = len(line)
        if n == 0:
            return []

        styles = [""] * n
        nospell = [False] * n

        def mark(a, b, cls):
            b = min(b, n)
            for i in range(max(a, 0), b):
                styles[i] = (styles[i] + " " + cls) if styles[i] else cls

        def shield(a, b):
            b = min(b, n)
            for i in range(max(a, 0), b):
                nospell[i] = True

        # Whole-line cases ----------------------------------------------------
        if in_fence:
            mark(0, n, "class:codeblock")
            return self._merge(styles, line)

        if HR_RE.match(line):
            mark(0, n, "class:hr")
            return self._merge(styles, line)

        hm = HEADER_RE.match(line)
        if hm:
            level = len(hm.group(1))
            mark(0, n, f"class:h{level}")
            mark(0, level, "class:marker")
        elif QUOTE_RE.match(line):
            mark(0, n, "class:quote")

        bm = BULLET_RE.match(line)
        if bm and not hm:
            mark(len(bm.group(1)), bm.end(), "class:bullet")

        # Inline spans ---------------------------------------------------------
        for m in INLINE_RE.finditer(line):
            a, b = m.span()
            if m.group("code") is not None:
                mark(a, a + 1, "class:marker")
                mark(a + 1, b - 1, "class:code")
                mark(b - 1, b, "class:marker")
                shield(a, b)
            elif m.group("bolditalic") is not None:
                mark(a, a + 3, "class:marker")
                mark(a + 3, b - 3, "class:bolditalic")
                mark(b - 3, b, "class:marker")
            elif m.group("bold") is not None or m.group("bold2") is not None:
                mark(a, a + 2, "class:marker")
                mark(a + 2, b - 2, "class:bold")
                mark(b - 2, b, "class:marker")
            elif m.group("italic") is not None or m.group("italic2") is not None:
                mark(a, a + 1, "class:marker")
                mark(a + 1, b - 1, "class:italic")
                mark(b - 1, b, "class:marker")
            elif m.group("strike") is not None:
                mark(a, a + 2, "class:marker")
                mark(a + 2, b - 2, "class:strike")
                mark(b - 2, b, "class:marker")
            elif m.group("underline") is not None:
                if m.group(0).startswith("<u>"):
                    lm, rm = 3, 4
                else:
                    lm, rm = 2, 2
                mark(a, a + lm, "class:marker")
                mark(a + lm, b - rm, "class:underline")
                mark(b - rm, b, "class:marker")
            elif m.group("linktext") is not None:
                ta, tb = m.span("linktext")
                ha, hb = m.span("linkhref")
                mark(a, ta, "class:marker")          # [
                mark(ta, tb, "class:link")
                mark(tb, ha, "class:marker")         # ](
                mark(ha, hb, "class:linkurl")
                mark(hb, b, "class:marker")          # )
                shield(ha, hb)
            elif m.group("url") is not None:
                mark(a, b, "class:linkurl")
                shield(a, b)

        # Spell overlay ----------------------------------------------------------
        if spell_on:
            words = [(w.group(), w.span()) for w in WORD_RE.finditer(line)]
            candidates = {
                w.lower()
                for w, (a, b) in words
                if self._spell_eligible(w) and not any(nospell[a:b])
            }
            if candidates:
                unknown = self.editor.unknown_words(candidates)
                for w, (a, b) in words:
                    if (
                        w.lower() in unknown
                        and self._spell_eligible(w)
                        and not any(nospell[a:b])
                    ):
                        mark(a, b, "class:misspelled")

        return self._merge(styles, line)

    # -- Lexer interface ----------------------------------------------------------

    def lex_document(self, document: Document):
        lines = document.lines
        flags = self._fence_flags(lines)
        spell_on = self.editor.spell_enabled
        dv = self.editor.dict_version

        if len(self._cache) > 8000:
            self._cache.clear()
        cache = self._cache

        def get_line(lineno: int):
            try:
                line = lines[lineno]
            except IndexError:
                return []
            key = (line, flags[lineno], spell_on, dv)
            frags = cache.get(key)
            if frags is None:
                frags = self._lex_line(line, flags[lineno], spell_on)
                cache[key] = frags
            return frags

        return get_line


# --------------------------------------------------------------------------
# Editor application
# --------------------------------------------------------------------------

class Editor:
    def __init__(self, filename=None, mouse=True, spell=True, input=None, output=None):
        # ---- state ----
        self.mouse_enabled = mouse
        self.spell_enabled = spell
        self.wrap_enabled = True
        self.help_visible = False
        self.mode = None          # None | open | saveas | confirm_quit | confirm_open | confirm_new
        self.pending = None       # e.g. "quit" after a forced save-as
        self.message = ""
        self.dict_version = 0
        self.word_count = 0

        # ---- spelling ----
        self.spell = SpellChecker()
        self.personal: set = set()
        self._known_cache: set = set()
        self._load_personal_dict()

        # ---- file / buffer ----
        self.filename = str(filename) if filename else None
        text = ""
        if self.filename and Path(self.filename).expanduser().exists():
            try:
                text = Path(self.filename).expanduser().read_text(encoding="utf-8")
            except Exception as e:
                self.message = f"Could not read {self.filename}: {e}"
        elif self.filename:
            self.message = f"New file: {self.filename}"

        self.saved_text = text
        self.buffer = Buffer(
            document=Document(text, 0),
            multiline=True,
            on_text_changed=self._on_text_changed,
        )
        self.word_count = len(WORD_RE.findall(text))

        # ---- suggestion popup state ----
        self.sugg_items: list | None = None
        self.sugg_index = 0
        self.sugg_word_span = None  # (row, col_a, col_b, original_word)

        # ---- widgets ----
        self.lexer = MarkdownSpellLexer(self)
        self.search_toolbar = SearchToolbar()
        self.buffer_control = BufferControl(
            buffer=self.buffer,
            lexer=self.lexer,
            search_buffer_control=self.search_toolbar.control,
            focus_on_click=True,
        )
        self.editor_window = Window(
            content=self.buffer_control,
            wrap_lines=Condition(lambda: self.wrap_enabled),
            left_margins=[NumberedMargin()],
            right_margins=[ScrollbarMargin(display_arrows=True)],
            cursorline=True,
        )

        # Minibuffer path prompt
        self.path_field = TextArea(
            multiline=False,
            style="class:minibar",
            accept_handler=self._accept_path,
        )
        prompt_bar = ConditionalContainer(
            VSplit(
                [
                    Window(
                        FormattedTextControl(lambda: [("class:minibar.label", self._prompt_label())]),
                        dont_extend_width=True,
                        height=1,
                        style="class:minibar",
                    ),
                    self.path_field,
                ]
            ),
            filter=Condition(lambda: self.mode in ("open", "saveas")),
        )

        # Confirmation bar
        self.confirm_control = FormattedTextControl(
            lambda: [("class:minibar.label", self._confirm_label())], focusable=True
        )
        confirm_bar = ConditionalContainer(
            Window(self.confirm_control, height=1, style="class:minibar"),
            filter=Condition(lambda: self.mode in ("confirm_quit", "confirm_open", "confirm_new")),
        )

        # Spelling-suggestion float
        self.sugg_control = FormattedTextControl(self._sugg_fragments, focusable=True)
        sugg_window = ConditionalContainer(
            Window(self.sugg_control, style="class:menu", dont_extend_width=True, dont_extend_height=True),
            filter=Condition(lambda: self.sugg_items is not None),
        )

        # Help float
        self.help_area = TextArea(
            text=HELP_TEXT, read_only=True, scrollbar=True, focusable=True,
            width=72, height=28, style="class:menu",
        )
        help_frame = ConditionalContainer(
            Frame(self.help_area, title="Essa Editor — keys"),
            filter=Condition(lambda: self.help_visible),
        )

        body = FloatContainer(
            content=self.editor_window,
            floats=[
                Float(content=sugg_window, xcursor=True, ycursor=True),
                Float(content=help_frame),
            ],
        )

        status_bar = VSplit(
            [
                Window(FormattedTextControl(self._status_left), style="class:status", height=1),
                Window(
                    FormattedTextControl(self._status_right),
                    style="class:status",
                    height=1,
                    align=WindowAlign.RIGHT,
                    dont_extend_width=True,
                ),
            ],
            height=1,
        )

        root = HSplit([body, self.search_toolbar, prompt_bar, confirm_bar, status_bar])

        self.app = Application(
            layout=Layout(root, focused_element=self.editor_window),
            key_bindings=self._build_keybindings(),
            style=STYLE,
            full_screen=True,
            mouse_support=Condition(lambda: self.mouse_enabled),
            clipboard=make_clipboard(),
            input=input,
            output=output,
        )

    # ----------------------------------------------------------------------
    # Spelling helpers
    # ----------------------------------------------------------------------

    def _load_personal_dict(self):
        try:
            if DICT_PATH.exists():
                self.personal = {
                    w.strip().lower() for w in DICT_PATH.read_text(encoding="utf-8").splitlines() if w.strip()
                }
        except Exception:
            self.personal = set()

    def add_to_dictionary(self, word: str):
        w = word.lower()
        self.personal.add(w)
        self._known_cache.add(w)
        try:
            DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with DICT_PATH.open("a", encoding="utf-8") as f:
                f.write(w + "\n")
        except Exception as e:
            self.message = f"Could not write dictionary: {e}"
            return
        self.dict_version += 1
        self.message = f"Added '{word}' to dictionary"

    def unknown_words(self, words: set) -> set:
        """Given lowercase words, return the subset the dictionary doesn't know."""
        todo = {w for w in words if w not in self.personal and w not in self._known_cache}
        if not todo:
            return set()
        unknown = self.spell.unknown(todo)
        self._known_cache.update(todo - unknown)
        return unknown

    def _misspelled_spans_in_line(self, line: str, in_fence: bool):
        if in_fence:
            return []
        spans = []
        words = [(m.group(), m.span()) for m in WORD_RE.finditer(line)]
        cands = {w.lower() for w, _ in words if len(w) >= 2 and not w.isupper()}
        unknown = self.unknown_words(cands)
        for w, (a, b) in words:
            if len(w) >= 2 and not w.isupper() and w.lower() in unknown:
                spans.append((a, b, w))
        return spans

    # ----------------------------------------------------------------------
    # Status bar / labels
    # ----------------------------------------------------------------------

    def _status_left(self):
        name = self.filename or "[untitled]"
        frags = [("class:status", " Essa Editor  "), ("class:status", name)]
        if self.modified:
            frags.append(("class:status.mod", " [+]"))
        if self.message:
            frags.append(("class:status.msg", f"   {self.message}"))
        return frags

    def _status_right(self):
        doc = self.buffer.document
        mouse = ("class:status", " Mouse:ON ") if self.mouse_enabled else ("class:status.off", " Mouse:OFF ")
        spell = ("class:status", " Spell:ON ") if self.spell_enabled else ("class:status.off", " Spell:OFF ")
        return [
            ("class:status", f" Ln {doc.cursor_position_row + 1}, Col {doc.cursor_position_col + 1} "),
            ("class:status", f"| W:{self.word_count} |"),
            mouse,
            ("class:status", "|"),
            spell,
            ("class:status", "| F1 Help "),
        ]

    def _prompt_label(self):
        return " Open file: " if self.mode == "open" else " Save as: "

    def _confirm_label(self):
        if self.mode == "confirm_quit":
            return " Unsaved changes — (s)ave and quit, (q)uit without saving, Esc cancel "
        if self.mode == "confirm_open":
            return " Unsaved changes — (y) discard and open, Esc cancel "
        if self.mode == "confirm_new":
            return " Unsaved changes — (y) discard and start new, Esc cancel "
        return ""

    @property
    def modified(self) -> bool:
        return self.buffer.text != self.saved_text

    def _on_text_changed(self, _buf):
        self.message = ""
        self.word_count = len(WORD_RE.findall(self.buffer.text))

    # ----------------------------------------------------------------------
    # File operations
    # ----------------------------------------------------------------------

    def _do_save(self, path: str) -> bool:
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.buffer.text, encoding="utf-8")
        except Exception as e:
            self.message = f"Save failed: {e}"
            return False
        self.filename = str(path)
        self.saved_text = self.buffer.text
        self.message = f"Saved {path}"
        return True

    def _do_open(self, path: str):
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8")
            self.message = f"Opened {path}"
        except FileNotFoundError:
            text = ""
            self.message = f"New file: {path}"
        except Exception as e:
            self.message = f"Open failed: {e}"
            return
        self.filename = str(path)
        self.saved_text = text
        self.buffer.document = Document(text, 0)
        self.word_count = len(WORD_RE.findall(text))

    def _accept_path(self, buf) -> bool:
        path = buf.text.strip()
        mode, self.mode = self.mode, None
        self.app.layout.focus(self.editor_window)
        if not path:
            self.message = "Cancelled"
            return False
        if mode == "open":
            self._do_open(path)
        elif mode == "saveas":
            ok = self._do_save(path)
            if ok and self.pending == "quit":
                self.app.exit()
        self.pending = None
        return False  # clear the input field

    def _enter_prompt(self, mode: str, prefill: str = ""):
        self.mode = mode
        self.path_field.text = prefill
        self.path_field.buffer.cursor_position = len(prefill)
        self.app.layout.focus(self.path_field)

    def _enter_confirm(self, mode: str):
        self.mode = mode
        self.app.layout.focus(self.confirm_control)

    def _leave_minibuffer(self):
        self.mode = None
        self.pending = None
        self.app.layout.focus(self.editor_window)

    # ----------------------------------------------------------------------
    # Formatting commands
    # ----------------------------------------------------------------------

    def toggle_inline(self, lm: str, rm: str):
        buf = self.buffer
        if buf.selection_state is not None:
            a = buf.selection_state.original_cursor_position
            b = buf.cursor_position
            start, end = min(a, b), max(a, b)
            buf.exit_selection()
            if start == end:
                return
            text = buf.text
            sel = text[start:end]
            buf.save_to_undo_stack()
            if sel.startswith(lm) and sel.endswith(rm) and len(sel) >= len(lm) + len(rm):
                new = sel[len(lm):len(sel) - len(rm)]
            elif text[max(0, start - len(lm)):start] == lm and text[end:end + len(rm)] == rm:
                start -= len(lm)
                end += len(rm)
                new = sel
            else:
                new = lm + sel + rm
            buf.document = Document(
                text[:start] + new + text[end:], cursor_position=start + len(new)
            )
        else:
            buf.save_to_undo_stack()
            buf.insert_text(lm + rm)
            buf.cursor_position -= len(rm)

    # ----------------------------------------------------------------------
    # Spelling commands
    # ----------------------------------------------------------------------

    def _word_under_cursor(self):
        doc = self.buffer.document
        row, col = doc.cursor_position_row, doc.cursor_position_col
        line = doc.lines[row]
        for m in WORD_RE.finditer(line):
            a, b = m.span()
            if a <= col <= b:
                return row, a, b, m.group()
        return None

    def open_suggestions(self):
        hit = self._word_under_cursor()
        if not hit:
            self.message = "No word under cursor"
            return
        row, a, b, word = hit
        if word.lower() in self.personal or not self.spell.unknown({word.lower()}):
            self.message = f"'{word}' looks fine"
            return
        try:
            cands = self.spell.candidates(word.lower()) or set()
        except Exception:
            cands = set()
        best = self.spell.correction(word.lower())
        ordered = []
        if best and best != word.lower():
            ordered.append(best)
        ordered += sorted(c for c in cands if c not in ordered and c != word.lower())
        if word[0].isupper():
            ordered = [c.capitalize() for c in ordered]
        self.sugg_items = ordered[:8] if ordered else []
        self.sugg_index = 0
        self.sugg_word_span = (row, a, b, word)
        self.app.layout.focus(self.sugg_control)

    def _sugg_fragments(self):
        if self.sugg_items is None:
            return []
        _, _, _, word = self.sugg_word_span
        frags = [("class:menu.title", f" '{word}' — Enter replace, a add to dict, Esc \n")]
        if not self.sugg_items:
            frags.append(("class:menu", " (no suggestions) \n"))
        for i, s in enumerate(self.sugg_items):
            style = "class:menu.selected" if i == self.sugg_index else "class:menu"
            frags.append((style, f"  {s}  \n"))
        return frags

    def close_suggestions(self):
        self.sugg_items = None
        self.sugg_word_span = None
        self.app.layout.focus(self.editor_window)

    def apply_suggestion(self):
        if not self.sugg_items:
            self.close_suggestions()
            return
        row, a, b, _ = self.sugg_word_span
        replacement = self.sugg_items[self.sugg_index]
        doc = self.buffer.document
        start = doc.translate_row_col_to_index(row, a)
        end = doc.translate_row_col_to_index(row, b)
        self.buffer.save_to_undo_stack()
        text = self.buffer.text
        self.buffer.document = Document(
            text[:start] + replacement + text[end:],
            cursor_position=start + len(replacement),
        )
        self.close_suggestions()

    def next_misspelled(self):
        doc = self.buffer.document
        lines = doc.lines
        flags = MarkdownSpellLexer._fence_flags(lines)
        row0, col0 = doc.cursor_position_row, doc.cursor_position_col
        order = list(range(row0, len(lines))) + list(range(0, row0 + 1))
        for idx, r in enumerate(order):
            for a, b, _w in self._misspelled_spans_in_line(lines[r], flags[r]):
                if idx == 0 and a <= col0:
                    continue
                self.buffer.cursor_position = doc.translate_row_col_to_index(r, a)
                return
        self.message = "No misspellings found"

    # ----------------------------------------------------------------------
    # Key bindings
    # ----------------------------------------------------------------------

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings()
        in_editor = has_focus(self.editor_window)
        in_prompt = has_focus(self.path_field)
        in_confirm = Condition(lambda: self.mode in ("confirm_quit", "confirm_open", "confirm_new"))
        in_sugg = Condition(lambda: self.sugg_items is not None)
        in_help = Condition(lambda: self.help_visible)

        # ---- global toggles ----
        @kb.add("f1")
        def _(event):
            self.help_visible = not self.help_visible
            event.app.layout.focus(self.help_area if self.help_visible else self.editor_window)

        @kb.add("f2")
        def _(event):
            self.mouse_enabled = not self.mouse_enabled
            self.message = (
                "Mouse ON — click/drag/scroll captured"
                if self.mouse_enabled
                else "Mouse OFF — native terminal selection active"
            )

        @kb.add("f3")
        def _(event):
            self.spell_enabled = not self.spell_enabled
            self.message = f"Spell check {'ON' if self.spell_enabled else 'OFF'}"

        @kb.add("f6")
        def _(event):
            self.wrap_enabled = not self.wrap_enabled
            self.message = f"Line wrap {'ON' if self.wrap_enabled else 'OFF'}"

        # ---- help ----
        @kb.add("escape", filter=in_help)
        @kb.add("q", filter=in_help)
        def _(event):
            self.help_visible = False
            event.app.layout.focus(self.editor_window)

        # ---- file ops (editor focus) ----
        @kb.add("c-s", filter=in_editor)
        def _(event):
            if self.filename:
                self._do_save(self.filename)
            else:
                self._enter_prompt("saveas")

        @kb.add("c-o", filter=in_editor)
        def _(event):
            if self.modified:
                self._enter_confirm("confirm_open")
            else:
                self._enter_prompt("open")

        @kb.add("c-n", filter=in_editor)
        def _(event):
            if self.modified:
                self._enter_confirm("confirm_new")
            else:
                self._new_buffer()

        @kb.add("c-q", filter=in_editor)
        def _(event):
            if self.modified:
                self._enter_confirm("confirm_quit")
            else:
                event.app.exit()

        # ---- formatting ----
        @kb.add("c-b", filter=in_editor)
        def _(event):
            self.toggle_inline("**", "**")

        @kb.add("escape", "i", filter=in_editor)
        def _(event):
            self.toggle_inline("*", "*")

        @kb.add("c-u", filter=in_editor)
        def _(event):
            self.toggle_inline("<u>", "</u>")

        # ---- editing ----
        @kb.add("c-z", filter=in_editor)
        def _(event):
            self.buffer.undo()

        @kb.add("c-f", filter=in_editor)
        def _(event):
            start_search(self.buffer_control)

        @kb.add("tab", filter=in_editor)
        def _(event):
            self.buffer.insert_text("    ")

        @kb.add("c-c", filter=in_editor)
        def _(event):
            data = self.buffer.copy_selection()
            event.app.clipboard.set_data(data)
            self.message = "Copied" if data.text else ""

        @kb.add("c-x", filter=in_editor)
        def _(event):
            self.buffer.save_to_undo_stack()
            data = self.buffer.cut_selection()
            event.app.clipboard.set_data(data)
            self.message = "Cut" if data.text else ""

        @kb.add("c-v", filter=in_editor)
        def _(event):
            self.buffer.save_to_undo_stack()
            self.buffer.paste_clipboard_data(event.app.clipboard.get_data())

        # ---- spelling ----
        @kb.add("f7", filter=in_editor)
        def _(event):
            self.open_suggestions()

        @kb.add("f8", filter=in_editor)
        def _(event):
            self.next_misspelled()

        # ---- suggestion popup ----
        @kb.add("up", filter=in_sugg)
        def _(event):
            if self.sugg_items:
                self.sugg_index = (self.sugg_index - 1) % len(self.sugg_items)

        @kb.add("down", filter=in_sugg)
        def _(event):
            if self.sugg_items:
                self.sugg_index = (self.sugg_index + 1) % len(self.sugg_items)

        @kb.add("enter", filter=in_sugg)
        def _(event):
            self.apply_suggestion()

        @kb.add("a", filter=in_sugg)
        def _(event):
            _, _, _, word = self.sugg_word_span
            self.add_to_dictionary(word)
            self.close_suggestions()

        @kb.add("escape", filter=in_sugg)
        @kb.add("f7", filter=in_sugg)
        def _(event):
            self.close_suggestions()

        # ---- path prompt ----
        @kb.add("escape", filter=in_prompt)
        def _(event):
            self.path_field.text = ""
            self._leave_minibuffer()
            self.message = "Cancelled"

        # ---- confirmation bar ----
        @kb.add("s", filter=in_confirm & Condition(lambda: self.mode == "confirm_quit"))
        def _(event):
            self.mode = None
            if self.filename:
                if self._do_save(self.filename):
                    event.app.exit()
                else:
                    self.app.layout.focus(self.editor_window)
            else:
                self.pending = "quit"
                self._enter_prompt("saveas")

        @kb.add("q", filter=in_confirm & Condition(lambda: self.mode == "confirm_quit"))
        def _(event):
            event.app.exit()

        @kb.add("y", filter=in_confirm & Condition(lambda: self.mode == "confirm_open"))
        def _(event):
            self.mode = None
            self._enter_prompt("open")

        @kb.add("y", filter=in_confirm & Condition(lambda: self.mode == "confirm_new"))
        def _(event):
            self._leave_minibuffer()
            self._new_buffer()

        @kb.add("escape", filter=in_confirm)
        @kb.add("n", filter=in_confirm)
        def _(event):
            self._leave_minibuffer()
            self.message = "Cancelled"

        return kb

    def _new_buffer(self):
        self.filename = None
        self.saved_text = ""
        self.buffer.document = Document("", 0)
        self.word_count = 0
        self.message = "New buffer"

    # ----------------------------------------------------------------------

    def run(self):
        self.app.run()


# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="essa", description="Terminal Markdown word processor with live styling and spell check."
    )
    parser.add_argument("file", nargs="?", help="Markdown file to open (created on save if missing)")
    parser.add_argument("--no-mouse", action="store_true", help="start with mouse capture disabled")
    parser.add_argument("--no-spell", action="store_true", help="start with spell check disabled")
    args = parser.parse_args(argv)

    editor = Editor(
        filename=args.file,
        mouse=not args.no_mouse,
        spell=not args.no_spell,
    )
    try:
        editor.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
