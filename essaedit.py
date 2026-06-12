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
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.formatted_text.utils import fragment_list_width
from prompt_toolkit.layout.utils import explode_text_fragments
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
from prompt_toolkit.layout.screen import _CHAR_CACHE
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.search import start_search
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
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

    def invalidation_hash(self):
        # BufferControl caches lexed lines by (document.text, lexer.invalidation_hash()).
        # Spell state and the personal dictionary change the output WITHOUT changing the
        # text, so fold them in here — otherwise toggling spell check off (F3) leaves
        # already-marked words red until the next edit.
        return (self.editor.spell_enabled, self.editor.dict_version)

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
# Word-aware soft wrap
#
# prompt_toolkit's Window wraps character-by-character (containers.py,
# Window._copy_body: `if wrap_lines and x + char_width > width`).  Two pieces
# must agree on where display rows break: _copy_body (rendering + the
# rowcol_to_yx cursor map) and UIContent.get_height_for_line (used by
# _scroll_when_linewrapping to keep the cursor in view).  Both are routed
# through one break computation below, so they cannot diverge.  The buffer is
# never modified — this is purely a display transform.  Cursor mapping needs
# no extra bookkeeping: rowcol_to_yx is keyed by *logical* column and built in
# the same render loop, so moving the break points moves the cells, not the
# mapping semantics.
#
# NOTE: WordWrapWindow._copy_body is a copy of prompt_toolkit 3.0.52's
# Window._copy_body with three marked changes.  If you upgrade prompt_toolkit
# past 3.0.x, re-diff against the new upstream before trusting it.
# --------------------------------------------------------------------------

_WRAP_BREAK_CACHE: dict = {}
_NO_BREAKS: frozenset = frozenset()


def _display_text(fragments) -> str:
    """Plain text of a rendered line in the same order _copy_body consumes
    characters: zero-width escape fragments are skipped, everything else kept."""
    parts = []
    for frag in fragments:
        if "[ZeroWidthEscape]" in frag[0]:
            continue
        parts.append(frag[1])
    return "".join(parts)


def _word_wrap_breaks(text: str, width: int) -> frozenset:
    """Greedy word wrap.  Returns the logical column indices where a new
    display row starts.  A break is placed after the last space/tab that fits
    on the row; a single token wider than the row (long URL, giant word) falls
    back to a character break so rendering can always make progress.  Widths
    come from wcwidth via get_cwidth, so emoji/CJK double-width cells are
    measured, not counted."""
    key = (text, width)
    cached = _WRAP_BREAK_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_WRAP_BREAK_CACHE) > 4096:
        _WRAP_BREAK_CACHE.clear()

    widths = [get_cwidth(c) for c in text]
    breaks = []
    x = 0            # display cells used on the current row
    row_start = 0    # logical column where the current row starts
    break_opp = None # column where a word break is allowed (char after whitespace)

    for col, c in enumerate(text):
        w = widths[col]
        if x + w > width and col > row_start:
            if break_opp is not None and break_opp > row_start:
                br = break_opp          # move the partial word down whole
            else:
                br = col                # token wider than the row: hard break
            breaks.append(br)
            row_start = br
            x = sum(widths[br:col])     # cells the carried word already uses
            break_opp = None
            if x + w > width and col > row_start:
                breaks.append(col)      # carried word + this char still too wide
                row_start = col
                x = 0
        if c in " \t":
            break_opp = col + 1
        x += w

    result = frozenset(breaks)
    _WRAP_BREAK_CACHE[key] = result
    return result


def _breaks_for_fragments(fragments, width: int) -> frozenset:
    if width <= 0:
        return _NO_BREAKS
    return _word_wrap_breaks(_display_text(fragments), width)


class WordWrapBufferControl(BufferControl):
    """BufferControl whose UIContent reports word-wrap-aware line heights.

    Window._scroll_when_linewrapping asks UIContent.get_height_for_line how
    many display rows each logical line occupies (and, via slice_stop, which
    display row the cursor sits on).  Those answers must match what
    WordWrapWindow actually renders, or scrolling drifts and the cursor can
    leave the viewport on long paragraphs."""

    def create_content(self, width, height, preview_search=False):
        content = super().create_content(width, height, preview_search)
        stock = content.get_height_for_line
        cache = content._line_heights_cache
        get_line = content.get_line

        def get_height_for_line(lineno, width, get_line_prefix, slice_stop=None):
            if get_line_prefix is not None:
                # Continuation prefixes change the usable width per row; this
                # editor doesn't use them, so defer to the stock estimate.
                return stock(lineno, width, get_line_prefix, slice_stop)
            key = ("wordwrap", get_app().render_counter, lineno, width, slice_stop)
            try:
                return cache[key]
            except KeyError:
                pass
            if width <= 0:
                h = 10**8
            else:
                breaks = _breaks_for_fragments(get_line(lineno), width)
                if slice_stop is None:
                    h = len(breaks) + 1
                else:
                    # Rows consumed by text before the cursor == breaks that
                    # fall strictly before it, plus the row it sits on.
                    h = sum(1 for b in breaks if b < slice_stop) + 1
            cache[key] = h
            return h

        content.get_height_for_line = get_height_for_line
        return content


class WordWrapWindow(Window):
    """Window that breaks soft-wrapped lines at word boundaries.

    _copy_body is copied from prompt_toolkit 3.0.52 Window._copy_body.
    Changes are marked with `# WORD-WRAP`.  Everything else — the cursor map
    (rowcol_to_yx), wide-char cell erasure, zero-width combining-character
    merging, line prefixes, alignment — is upstream code, untouched."""

    def _copy_body(
        self,
        ui_content,
        new_screen,
        write_position,
        move_x,
        width,
        vertical_scroll=0,
        horizontal_scroll=0,
        wrap_lines=False,
        highlight_lines=False,
        vertical_scroll_2=0,
        always_hide_cursor=False,
        has_focus=False,
        align=WindowAlign.LEFT,
        get_line_prefix=None,
    ):
        xpos = write_position.xpos + move_x
        ypos = write_position.ypos
        line_count = ui_content.line_count
        new_buffer = new_screen.data_buffer
        empty_char = _CHAR_CACHE["", ""]

        # Map visible line number to (row, col) of input.
        # 'col' will always be zero if line wrapping is off.
        visible_line_to_row_col = {}

        # Maps (row, col) from the input to (y, x) screen coordinates.
        rowcol_to_yx = {}

        def copy_line(line, lineno, x, y, is_input=False, breaks=_NO_BREAKS):  # WORD-WRAP: breaks arg
            """
            Copy over a single line to the output screen. This can wrap over
            multiple lines in the output. It will call the prefix (prompt)
            function before every line.
            """
            if is_input:
                current_rowcol_to_yx = rowcol_to_yx
            else:
                current_rowcol_to_yx = {}  # Throwaway dictionary.

            # Draw line prefix.
            if is_input and get_line_prefix:
                prompt = to_formatted_text(get_line_prefix(lineno, 0))
                x, y = copy_line(prompt, lineno, x, y, is_input=False)

            # Scroll horizontally.
            skipped = 0  # Characters skipped because of horizontal scrolling.
            if horizontal_scroll and is_input:
                h_scroll = horizontal_scroll
                line = explode_text_fragments(line)
                while h_scroll > 0 and line:
                    h_scroll -= get_cwidth(line[0][1])
                    skipped += 1
                    del line[:1]  # Remove first character.

                x -= h_scroll  # When scrolling over double width character,
                # this can end up being negative.

            # Align this line. (Note that this doesn't work well when we use
            # get_line_prefix and that function returns variable width prefixes.)
            if align == WindowAlign.CENTER:
                line_width = fragment_list_width(line)
                if line_width < width:
                    x += (width - line_width) // 2
            elif align == WindowAlign.RIGHT:
                line_width = fragment_list_width(line)
                if line_width < width:
                    x += width - line_width

            col = 0
            wrap_count = 0
            for style, text, *_ in line:
                new_buffer_row = new_buffer[y + ypos]

                # Remember raw VT escape sequences. (E.g. FinalTerm's
                # escape sequences.)
                if "[ZeroWidthEscape]" in style:
                    new_screen.zero_width_escapes[y + ypos][x + xpos] += text
                    continue

                for c in text:
                    char = _CHAR_CACHE[c, style]
                    char_width = char.width

                    # WORD-WRAP: break at precomputed word boundaries; the
                    # original char-level check stays as a safety net.
                    if wrap_lines and (col in breaks or x + char_width > width):
                        visible_line_to_row_col[y + 1] = (
                            lineno,
                            # WORD-WRAP: record the true logical start column
                            # of the continuation row (exact for wide chars).
                            col if is_input else visible_line_to_row_col[y][1] + x,
                        )
                        y += 1
                        wrap_count += 1
                        x = 0

                        # Insert line prefix (continuation prompt).
                        if is_input and get_line_prefix:
                            prompt = to_formatted_text(
                                get_line_prefix(lineno, wrap_count)
                            )
                            x, y = copy_line(prompt, lineno, x, y, is_input=False)

                        new_buffer_row = new_buffer[y + ypos]

                        if y >= write_position.height:
                            return x, y  # Break out of all for loops.

                    # Set character in screen and shift 'x'.
                    if x >= 0 and y >= 0 and x < width:
                        new_buffer_row[x + xpos] = char

                        # When we print a multi width character, make sure
                        # to erase the neighbors positions in the screen.
                        # (The empty string if different from everything,
                        # so next redraw this cell will repaint anyway.)
                        if char_width > 1:
                            for i in range(1, char_width):
                                new_buffer_row[x + xpos + i] = empty_char

                        # If this is a zero width characters, then it's
                        # probably part of a decomposed unicode character.
                        # See: https://en.wikipedia.org/wiki/Unicode_equivalence
                        # Merge it in the previous cell.
                        elif char_width == 0:
                            # Handle all character widths. If the previous
                            # character is a multiwidth character, then
                            # merge it two positions back.
                            for pw in [2, 1]:  # Previous character width.
                                if (
                                    x - pw >= 0
                                    and new_buffer_row[x + xpos - pw].width == pw
                                ):
                                    prev_char = new_buffer_row[x + xpos - pw]
                                    char2 = _CHAR_CACHE[
                                        prev_char.char + c, prev_char.style
                                    ]
                                    new_buffer_row[x + xpos - pw] = char2

                        # Keep track of write position for each character.
                        current_rowcol_to_yx[lineno, col + skipped] = (
                            y + ypos,
                            x + xpos,
                        )

                    col += 1
                    x += char_width
            return x, y

        # Copy content.
        def copy():
            y = -vertical_scroll_2
            lineno = vertical_scroll

            while y < write_position.height and lineno < line_count:
                # Take the next line and copy it in the real screen.
                line = ui_content.get_line(lineno)

                visible_line_to_row_col[y] = (lineno, horizontal_scroll)

                # WORD-WRAP: compute break columns for this logical line.
                if wrap_lines:
                    line_breaks = _breaks_for_fragments(line, width)
                else:
                    line_breaks = _NO_BREAKS

                # Copy margin and actual line.
                x = 0
                x, y = copy_line(line, lineno, x, y, is_input=True, breaks=line_breaks)

                lineno += 1
                y += 1
            return y

        copy()

        def cursor_pos_to_screen_pos(row, col):
            "Translate row/col from UIContent to real Screen coordinates."
            try:
                y, x = rowcol_to_yx[row, col]
            except KeyError:
                # Normally this should never happen. (It is a bug, if it happens.)
                # But to be sure, return (0, 0)
                return Point(x=0, y=0)
            else:
                return Point(x=x, y=y)

        # Set cursor and menu positions.
        if ui_content.cursor_position:
            screen_cursor_position = cursor_pos_to_screen_pos(
                ui_content.cursor_position.y, ui_content.cursor_position.x
            )

            if has_focus:
                new_screen.set_cursor_position(self, screen_cursor_position)

                if always_hide_cursor:
                    new_screen.show_cursor = False
                else:
                    new_screen.show_cursor = ui_content.show_cursor

                self._highlight_digraph(new_screen)

            if highlight_lines:
                self._highlight_cursorlines(
                    new_screen,
                    screen_cursor_position,
                    xpos,
                    ypos,
                    width,
                    write_position.height,
                )

        # Draw input characters from the input processor queue.
        if has_focus and ui_content.cursor_position:
            self._show_key_processor_key_buffer(new_screen)

        # Set menu position.
        if ui_content.menu_position:
            new_screen.set_menu_position(
                self,
                cursor_pos_to_screen_pos(
                    ui_content.menu_position.y, ui_content.menu_position.x
                ),
            )

        # Update output screen height.
        new_screen.height = max(new_screen.height, ypos + write_position.height)

        return visible_line_to_row_col, rowcol_to_yx


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
        self.buffer_control = WordWrapBufferControl(
            buffer=self.buffer,
            lexer=self.lexer,
            search_buffer_control=self.search_toolbar.control,
            focus_on_click=True,
        )
        self.editor_window = WordWrapWindow(
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
