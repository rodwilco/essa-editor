"""Word-wrap verification for Essa Editor. Renders through the real pipeline."""
import asyncio

from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.utils import get_cwidth

import essaedit


def render(ed, width, height=200, wrap=True):
    """Run create_content + _copy_body exactly as the Window would.
    Executed inside an event loop because Buffer history loading needs one."""
    async def go():
        return ed.buffer_control.create_content(width, height)
    content = asyncio.run(go())
    screen = Screen()
    wp = WritePosition(xpos=0, ypos=0, width=width, height=height)
    vis, rowcol = ed.editor_window._copy_body(
        content, screen, wp, move_x=0, width=width, wrap_lines=wrap
    )
    return content, screen, vis, rowcol


def screen_rows(screen, width, nrows):
    rows = []
    for y in range(nrows):
        row = screen.data_buffer[y]
        rows.append("".join(row[x].char for x in range(width)).rstrip())
    return rows


def make_editor(text):
    ed = essaedit.Editor(output=DummyOutput())
    ed.buffer.document = Document(text, 0)
    return ed


def test_word_boundaries():
    W = 30
    text = (
        "The quick brown fox jumps over the lazy dog repeatedly until "
        "everyone involved is thoroughly exhausted by the demonstration."
    )
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W)
    h = content.get_height_for_line(0, W, None)
    rows = screen_rows(screen, W, h)
    print("rendered rows:")
    for r in rows:
        print(f"  |{r}|")
    words = set(text.split())
    for r in rows:
        assert len(r) <= W
        for piece in r.split():
            assert piece in words, f"word split across rows: {piece!r}"
    # reassembling rows must give back the text (modulo whitespace at breaks)
    assert " ".join(" ".join(rows).split()) == " ".join(text.split())
    print("word boundaries OK")


def test_cursor_map_complete():
    W = 25
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa\nshort\nanother wrapping line with several words here"
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W)
    # Every cursor-reachable (row, col) must map to a screen cell:
    # cols 0..len(line) inclusive (BufferControl pads EOL for the cursor).
    for lineno, line in enumerate(text.split("\n")):
        for col in range(len(line) + 1):
            assert (lineno, col) in rowcol, f"unmapped cursor position {(lineno, col)}"
    # Screen y must be strictly non-decreasing with col (no mapping disorder)
    for lineno, line in enumerate(text.split("\n")):
        ys = [rowcol[(lineno, c)][0] for c in range(len(line) + 1)]
        assert ys == sorted(ys), f"y not monotonic on line {lineno}: {ys}"
    print("cursor map complete and monotonic OK")


def test_heights_agree_with_render():
    W = 22
    text = (
        "one paragraph that is fairly long and wraps multiple times for sure\n"
        "x\n"
        "\n"
        "Supercalifragilisticexpialidocious_is_one_enormous_token_no_spaces_anywhere\n"
        "tail words here"
    )
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W)
    # rows actually used per logical line, from the visible-line map
    from collections import Counter
    used = Counter(lineno for (lineno, _col) in vis.values())
    for lineno in range(content.line_count):
        h = content.get_height_for_line(lineno, W, None)
        assert h == used[lineno], f"line {lineno}: height calc {h} != rendered {used[lineno]}"
    print("get_height_for_line == rendered rows for every line OK")


def test_long_token_fallback():
    W = 20
    token = "a" * 55
    ed = make_editor(f"start {token} end")
    content, screen, vis, rowcol = render(ed, W)
    h = content.get_height_for_line(0, W, None)
    rows = screen_rows(screen, W, h)
    joined = "".join(rows)
    assert token in joined.replace(" ", "") or token in "".join(r.strip() for r in rows), rows
    assert all(len(r) <= W for r in rows)
    assert h >= 4  # 55 chars cannot fit in fewer than 3 rows of 20 + surrounding words
    print("oversize token falls back to char wrap OK")


def test_wide_chars():
    W = 12
    text = "ab 🙂🙂🙂 cd 🙂🙂🙂🙂🙂🙂 efgh"
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W)
    h = content.get_height_for_line(0, W, None)
    # display width of every rendered row must be <= W
    for y in range(h):
        row = screen.data_buffer[y]
        used = 0
        x = 0
        while x < W:
            ch = row[x].char
            w = max(1, get_cwidth(ch)) if ch else 1
            if ch and ch != " ":
                used = x + get_cwidth(ch)
            x += 1
        assert used <= W, f"row {y} overflows: {used} > {W}"
    # all logical cols mapped
    for col in range(len(text) + 1):
        assert (0, col) in rowcol, f"unmapped col {col} (emoji line)"
    print("emoji/wide chars OK")


def test_slice_stop_matches_cursor_row():
    W = 18
    text = "many small words flow along this line and keep flowing for a while longer"
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W)
    for col in range(0, len(text) + 1, 5):
        h_before = content.get_height_for_line(0, W, None, slice_stop=col)
        actual_row = rowcol[(0, col)][0]
        assert h_before == actual_row + 1, (
            f"slice_stop={col}: scroll math says row {h_before - 1}, render says {actual_row}"
        )
    print("slice_stop agrees with actual cursor row OK")


def test_styling_preserved():
    """Markdown lexer styles must survive the new window: check the styled
    char cells carry the classes."""
    W = 40
    ed = make_editor("This has **bold** and *italic* and a mispelled wrod here")
    content, screen, vis, rowcol = render(ed, W)
    styles = set()
    for y in range(6):
        row = screen.data_buffer[y]
        for x in range(W):
            styles.add(row[x].style)
    blob = " ".join(styles)
    for cls in ("class:bold", "class:italic", "class:marker", "class:misspelled"):
        assert cls in blob, f"{cls} missing after word-wrap render"
    print("inline styling preserved OK")


def test_wrap_off_unchanged():
    W = 15
    text = "a very long line that would normally wrap"
    ed = make_editor(text)
    content, screen, vis, rowcol = render(ed, W, wrap=False)
    # No wrapping: a single visible row for the line
    assert all(lineno == 0 for (lineno, _c) in vis.values())
    assert len(vis) == 1
    print("wrap-off path untouched OK")


def test_f6_and_full_app():
    async def runner():
        with create_pipe_input() as pipe:
            ed = essaedit.Editor(input=pipe, output=DummyOutput())
            ed.buffer.document = Document("word " * 50, 0)
            ed.saved_text = ed.buffer.text

            async def drive():
                await asyncio.sleep(0.3)
                w0 = ed.wrap_enabled
                pipe.send_text("\x1b[17~")  # F6
                await asyncio.sleep(0.3)
                assert ed.wrap_enabled != w0
                pipe.send_text("\x1b[17~")  # F6 back
                await asyncio.sleep(0.3)
                assert ed.wrap_enabled == w0
                pipe.send_text("\x11")      # Ctrl+Q, unmodified -> exits

            t = asyncio.get_event_loop().create_task(drive())
            await asyncio.wait_for(ed.app.run_async(), timeout=10)
            await t

    asyncio.run(runner())
    print("F6 toggle + full app run OK")


if __name__ == "__main__":
    test_word_boundaries()
    test_cursor_map_complete()
    test_heights_agree_with_render()
    test_long_token_fallback()
    test_wide_chars()
    test_slice_stop_matches_cursor_row()
    test_styling_preserved()
    test_wrap_off_unchanged()
    test_f6_and_full_app()
    print("ALL WORD-WRAP TESTS PASSED")
