<p align="center">
  <img src="logo.png" alt="Essa Editor" width="420">
</p>

# Essa Editor

A terminal Markdown word processor. Single Python file, pure-Python dependencies, works in a bare TTY or over SSH.

```
        _.._
       /   _ `.
      /  /   `.\
     |  |      `>_
  > ~~~~~~~~~~~~~~~~~~
    E S S A   E D I T O R
```

## Features

- **Live inline styling (WYSIWYG):** `**bold**` renders bold, `*italic*` renders italic, `<u>underline</u>` (or `++underline++`) renders underlined — as you type. Markers stay visible but dimmed, so cursor positions always map 1:1 to the file on disk. Headers, lists, blockquotes, inline/fenced code, links, and `~~strikethrough~~` are also styled.
- **Spell check:** misspellings get a red underline. F7 opens a suggestion popup (Enter replaces, `a` adds the word to a personal dictionary), F8 jumps to the next misspelling, F3 toggles checking. Code spans, fenced blocks, URLs, and ALL-CAPS acronyms are skipped.
- **Toggleable mouse (F2):** ON = click to place the cursor, drag to select, wheel to scroll. OFF = the editor releases the mouse so your terminal's native selection and copy/paste work.
- **256-color theme**, line numbers, current-line highlight, soft wrap (F6), incremental search (Ctrl+F), undo, cut/copy/paste.

## Install

Dependencies are `prompt_toolkit` and `pyspellchecker` (both pure Python, no compilation). On Debian/Ubuntu the system Python is externally managed, so use a venv:

```
python3 -m venv ~/.local/share/essaedit-venv
~/.local/share/essaedit-venv/bin/pip install -r requirements.txt
```

Then make it callable. For **fish**:

```
alias --save essaedit "~/.local/share/essaedit-venv/bin/python3 /path/to/essaedit.py"
```

For **bash/zsh**, add to your `~/.bashrc` / `~/.zshrc`:

```
alias essaedit='~/.local/share/essaedit-venv/bin/python3 /path/to/essaedit.py'
```

Or just `chmod +x essaedit.py` and point the shebang at the venv python.

Optional: `pip install pyperclip` lets Ctrl+C/X/V use the system clipboard instead of the internal one. This needs a graphical session — `apt install xclip` on X11, or `wl-clipboard` on Wayland. On a bare TTY (no X/Wayland) there's no system clipboard; the internal clipboard works fine there.

## Usage

```
essaedit notes.md          # opens (or creates on save)
essaedit --no-mouse        # start with mouse capture off
essaedit --no-spell        # start with spell check off
```

## Keys

| Key | Action |
|---|---|
| Ctrl+S | Save (prompts for a name if untitled) |
| Ctrl+O | Open file |
| Ctrl+N | New buffer |
| Ctrl+Q | Quit (asks about unsaved changes) |
| Ctrl+B | Bold — wraps selection in `**`, or inserts markers |
| Alt+I | Italic (Ctrl+I is indistinguishable from Tab in terminals) |
| Ctrl+U | Underline (`<u>…</u>`) |
| Ctrl+Z | Undo |
| Ctrl+X / C / V | Cut / Copy / Paste |
| Ctrl+F | Search (Enter = next match, Esc = cancel) |
| Tab | Insert 4 spaces |
| F1 | Help overlay |
| F2 | Toggle mouse capture |
| F3 | Toggle spell check |
| F6 | Toggle soft wrap |
| F7 | Spelling suggestions for word under cursor |
| F8 | Jump to next misspelled word |

Formatting keys toggle: select already-wrapped text (with or without the markers) and press the key again to unwrap.

## Notes

- The personal dictionary lives at `~/.config/essaedit/dictionary.txt`, one word per line. Edit it freely.
- Underline isn't part of standard Markdown; `<u>` tags are the portable convention and survive most renderers. `++text++` is also styled for editors that use that extension.
- Inline markers must open and close on the same line to render (line-based lexer).
- `snake_case_identifiers` are not treated as italics — underscore emphasis only triggers at word boundaries.
- Files are read and written as UTF-8.

## License

[GNU General Public License v3.0 or later](LICENSE). Copyright (C) 2026 Colin Lewis.
