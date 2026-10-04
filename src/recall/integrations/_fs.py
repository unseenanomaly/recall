"""Small, reversible file operations used by ``recall install`` / ``recall uninstall``.

Every change Recall makes to another tool's config is one of these actions, and every
action knows how to undo itself, so ``uninstall`` removes exactly what ``install``
added and nothing else:

* :class:`Tree`      a directory Recall owns (marked with ``.recall-managed``)
* :class:`File`      a single file Recall owns
* :class:`JsonEntry` one key in someone else's JSON config (``mcpServers.recall``)
* :class:`JsonHooks` hook entries in a JSON hooks list, recognised by a marker
* :class:`TextBlock` a fenced block in a TOML/Markdown file (``# >>> recall >>>``)
* :class:`Run`       an external command (e.g. ``hermes plugins enable recall``)
* :class:`Note`      a step the user has to do by hand

A pre-existing config file is copied to ``<file>.recall-backup`` before its first edit.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..store import replace_file

MARKER_FILE = ".recall-managed"
BEGIN, END = ">>> recall >>>", "<<< recall <<<"


class Manual(Exception):
    """The change can't be made automatically; the message says how to do it by hand."""


@dataclass
class Line:
    status: str   # "+" added, "~" updated, "-" removed, "=" unchanged, "!" manual step, "x" failed
    text: str

    def __str__(self) -> str:
        return f"  {self.status} {self.text}"


def _tilde(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".recall-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    replace_file(tmp, path)


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _backup(path: str) -> None:
    bak = path + ".recall-backup"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)


_COMMENT = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING = re.compile(r",(\s*[}\]])")


def load_json(path: str) -> Tuple[Dict[str, Any], bool]:
    """(data, existed). Raises Manual if the file has comments (we won't destroy them)."""
    text = _read(path)
    if text is None or not text.strip():
        return {}, text is not None
    try:
        data = json.loads(text)
    except ValueError:
        relaxed = _TRAILING.sub(r"\1", _COMMENT.sub(lambda m: m.group(1) or "", text))
        try:
            json.loads(relaxed)
        except ValueError:
            raise Manual(f"{_tilde(path)} isn't valid JSON; fix it, then re-run, or edit it by hand")
        raise Manual(f"{_tilde(path)} contains comments, which an automatic edit would erase")
    if not isinstance(data, dict):
        raise Manual(f"{_tilde(path)} doesn't contain a JSON object")
    return data, True


def save_json(path: str, data: Dict[str, Any], existed: bool) -> None:
    if existed:
        _backup(path)
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


class Action:
    def apply(self, dry: bool = False) -> List[Line]:
        raise NotImplementedError

    def undo(self, dry: bool = False) -> List[Line]:
        raise NotImplementedError

    def present(self) -> Optional[bool]:
        return None

    def preview(self) -> str:
        return ""


@dataclass
class Tree(Action):
    root: str
    files: Dict[str, str]
    label: str = ""

    def apply(self, dry: bool = False) -> List[Line]:
        out = []
        if os.path.isdir(self.root) and not os.path.exists(os.path.join(self.root, MARKER_FILE)) \
                and os.listdir(self.root):
            bak = self.root + ".recall-backup"
            out.append(Line("~", f"moved existing {_tilde(self.root)} to {_tilde(bak)}"))
            if not dry:
                if os.path.exists(bak):
                    shutil.rmtree(bak)
                os.replace(self.root, bak)
        status = "~" if os.path.isdir(self.root) else "+"
        if not dry:
            if os.path.isdir(self.root):
                shutil.rmtree(self.root)
            for rel, text in self.files.items():
                _write(os.path.join(self.root, *rel.split("/")), text)
            _write(os.path.join(self.root, MARKER_FILE), "Installed by `recall install`. "
                                                         "`recall uninstall` deletes this folder.\n")
        out.append(Line(status, f"{_tilde(self.root)}/  {self.label or f'({len(self.files)} files)'}"))
        return out

    def undo(self, dry: bool = False) -> List[Line]:
        if not os.path.isdir(self.root):
            return []
        if not os.path.exists(os.path.join(self.root, MARKER_FILE)):
            return [Line("!", f"left {_tilde(self.root)} alone (not created by recall)")]
        if not dry:
            shutil.rmtree(self.root)
        return [Line("-", f"{_tilde(self.root)}/")]

    def present(self) -> bool:
        return os.path.exists(os.path.join(self.root, MARKER_FILE))


@dataclass
class File(Action):
    path: str
    content: str
    label: str = ""

    def apply(self, dry: bool = False) -> List[Line]:
        old = _read(self.path)
        if old == self.content:
            return [Line("=", _tilde(self.path))]
        if not dry:
            _write(self.path, self.content)
        return [Line("~" if old is not None else "+", f"{_tilde(self.path)}  {self.label}".rstrip())]

    def undo(self, dry: bool = False) -> List[Line]:
        if not os.path.exists(self.path):
            return []
        if not dry:
            os.remove(self.path)
            parent = os.path.dirname(self.path)
            try:
                if "recall" in os.path.basename(parent) and not os.listdir(parent):
                    os.rmdir(parent)
            except OSError:
                pass
        return [Line("-", _tilde(self.path))]

    def present(self) -> bool:
        return os.path.exists(self.path)


def _dig(data: Dict[str, Any], keys: Sequence[str], create: bool) -> Optional[Dict[str, Any]]:
    cur = data
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            if not create:
                return None
            nxt = cur[k] = {}
        cur = nxt
    return cur


@dataclass
class JsonEntry(Action):
    path: str
    keys: Tuple[str, ...]
    value: Any
    seed: Dict[str, Any] = field(default_factory=dict)   # top-level keys for a brand-new file

    def apply(self, dry: bool = False) -> List[Line]:
        where = f"{_tilde(self.path)}  ({'.'.join(self.keys)})"
        try:
            data, existed = load_json(self.path)
        except Manual as e:
            return [Line("!", f"{e}. Add this under {'.'.join(self.keys)}:\n{self.preview()}")]
        if not existed or not data:
            data = {**self.seed, **data}
        parent = _dig(data, self.keys, create=True)
        if parent.get(self.keys[-1]) == self.value:
            return [Line("=", where)]
        ours = self.keys[-1] in parent          # already edited by recall: nothing new to back up
        status = "~" if ours else "+"
        parent[self.keys[-1]] = self.value
        if not dry:
            save_json(self.path, data, existed and not ours)
        return [Line(status, where)]

    def undo(self, dry: bool = False) -> List[Line]:
        try:
            data, existed = load_json(self.path)
        except Manual as e:
            return [Line("!", f"{e}. Remove {'.'.join(self.keys)} by hand")]
        parent = _dig(data, self.keys, create=False)
        if not existed or parent is None or self.keys[-1] not in parent:
            return []
        del parent[self.keys[-1]]
        for depth in range(len(self.keys) - 1, 0, -1):     # drop containers we emptied ({"mcp": {"servers": {}}})
            holder = _dig(data, self.keys[:depth], create=False)
            if holder is not None and holder.get(self.keys[depth - 1]) == {}:
                del holder[self.keys[depth - 1]]
        if not dry:
            remaining = {k: v for k, v in data.items() if k not in self.seed}
            if not remaining and not os.path.exists(self.path + ".recall-backup"):
                os.remove(self.path)
            else:
                _write(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return [Line("-", f"{_tilde(self.path)}  ({'.'.join(self.keys)})")]

    def present(self) -> bool:
        try:
            data, _ = load_json(self.path)
        except Manual:
            return False
        parent = _dig(data, self.keys, create=False)
        return parent is not None and self.keys[-1] in parent

    def preview(self) -> str:
        snippet: Any = self.value
        for k in reversed(self.keys):
            snippet = {k: snippet}
        return json.dumps(snippet, indent=2)


@dataclass
class JsonHooks(Action):
    """Hook entries inside a JSON file's ``hooks`` map. Our entries are recognised by
    ``marker`` (e.g. ``--agent codex``) appearing in their command."""

    path: str
    events: Dict[str, List[Dict[str, Any]]]
    marker: str
    seed: Dict[str, Any] = field(default_factory=dict)

    def _strip(self, hooks: Dict[str, Any]) -> int:
        removed = 0
        for ev in list(hooks):
            lst = hooks[ev]
            if not isinstance(lst, list):
                continue
            keep = [e for e in lst if self.marker not in json.dumps(e)]
            removed += len(lst) - len(keep)
            if keep:
                hooks[ev] = keep
            else:
                del hooks[ev]
        return removed

    def apply(self, dry: bool = False) -> List[Line]:
        try:
            data, existed = load_json(self.path)
        except Manual as e:
            return [Line("!", f"{e}. Add these hooks by hand:\n{self.preview()}")]
        if not existed or not data:
            data = {**self.seed, **data}
        hooks = data.setdefault("hooks", {})
        had = self._strip(hooks)
        for ev, entries in self.events.items():
            hooks.setdefault(ev, []).extend(entries)
        if not dry:
            save_json(self.path, data, existed and not had)
        return [Line("~" if had else "+", f"{_tilde(self.path)}  (hooks: {', '.join(self.events)})")]

    def undo(self, dry: bool = False) -> List[Line]:
        try:
            data, existed = load_json(self.path)
        except Manual as e:
            return [Line("!", f"{e}. Remove the hooks that run `recall hook` by hand")]
        hooks = data.get("hooks")
        if not existed or not isinstance(hooks, dict) or not self._strip(hooks):
            return []
        if not hooks:
            del data["hooks"]
        if not dry:
            remaining = {k: v for k, v in data.items() if k not in self.seed}
            if not remaining and not os.path.exists(self.path + ".recall-backup"):
                os.remove(self.path)
            else:
                _write(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return [Line("-", f"{_tilde(self.path)}  (recall hooks)")]

    def present(self) -> bool:
        try:
            data, _ = load_json(self.path)
        except Manual:
            return False
        return self.marker in json.dumps(data.get("hooks", {}))

    def preview(self) -> str:
        return json.dumps({"hooks": self.events}, indent=2)


@dataclass
class TextBlock(Action):
    """A fenced block in a text file. ``guard(text_outside_block)`` may raise Manual."""

    path: str
    block: str
    style: str = "#"            # "#" for TOML/YAML, "html" for Markdown
    guard: Optional[Callable[[str], None]] = None
    label: str = ""

    def _fences(self) -> Tuple[str, str]:
        if self.style == "html":
            return f"<!-- {BEGIN} -->", f"<!-- {END} -->"
        return f"# {BEGIN} (managed by `recall install`; `recall uninstall` removes it)", f"# {END}"

    def _split(self, text: str) -> Tuple[str, Optional[str], str]:
        b, e = self._fences()
        rx = re.compile(re.escape(b.split(" (")[0]) + r".*?" + re.escape(e) + r"\n?", re.S)
        m = rx.search(text)
        if not m:
            return text, None, ""
        return text[:m.start()], m.group(0), text[m.end():]

    def apply(self, dry: bool = False) -> List[Line]:
        old = _read(self.path)
        before, current, after = self._split(old or "")
        b, e = self._fences()
        block = f"{b}\n{self.block.rstrip()}\n{e}\n"
        if current == block:
            return [Line("=", _tilde(self.path))]
        if self.guard:
            try:
                self.guard(before + after)
            except Manual as err:
                return [Line("!", f"{_tilde(self.path)}: {err}. Add this by hand:\n{self.block}")]
        if current is None:
            sep = "" if not before.strip() else ("\n" if before.endswith("\n") else "\n\n")
            new = before + sep + block
        else:
            new = before + block + after
        if not dry:
            if old is not None and current is None:
                _backup(self.path)
            _write(self.path, new)
        return [Line("~" if current else "+", f"{_tilde(self.path)}  {self.label}".rstrip())]

    def undo(self, dry: bool = False) -> List[Line]:
        old = _read(self.path)
        if old is None:
            return []
        before, current, after = self._split(old)
        if current is None:
            return []
        rest = (before.rstrip("\n") + "\n" + after.lstrip("\n")).strip("\n")
        if not dry:
            if rest.strip():
                _write(self.path, rest + "\n")
            else:
                os.remove(self.path)
        return [Line("-", f"{_tilde(self.path)}  (recall block)")]

    def present(self) -> bool:
        return self._split(_read(self.path) or "")[1] is not None

    def preview(self) -> str:
        return self.block


@dataclass
class Run(Action):
    argv: List[str]
    undo_argv: Optional[List[str]] = None
    why: str = ""

    def _exec(self, argv: List[str], dry: bool) -> List[Line]:
        exe = shutil.which(argv[0])
        shown = " ".join(argv)
        if not exe:
            return [Line("!", f"run `{shown}` once {argv[0]} is installed{(' (' + self.why + ')') if self.why else ''}")]
        if dry:
            return [Line("+", f"would run `{shown}`")]
        try:
            p = subprocess.run([exe] + argv[1:], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            return [Line("x", f"`{shown}` failed: {e}")]
        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "").strip().splitlines()
            return [Line("x", f"`{shown}` exited {p.returncode}: {msg[-1] if msg else ''}")]
        return [Line("+", f"ran `{shown}`")]

    def apply(self, dry: bool = False) -> List[Line]:
        return self._exec(self.argv, dry)

    def undo(self, dry: bool = False) -> List[Line]:
        return self._exec(self.undo_argv, dry) if self.undo_argv else []


@dataclass
class Note(Action):
    text: str
    on_uninstall: str = ""

    def apply(self, dry: bool = False) -> List[Line]:
        return [Line("!", self.text)]

    def undo(self, dry: bool = False) -> List[Line]:
        return [Line("!", self.on_uninstall)] if self.on_uninstall else []


@dataclass
class Files(Action):
    """Several small files Recall owns (e.g. one per slash command), reported as one line."""

    paths: Dict[str, str]          # absolute path -> content
    label: str = ""

    def apply(self, dry: bool = False) -> List[Line]:
        changed = [p for p, t in self.paths.items() if _read(p) != t]
        if not changed:
            return [Line("=", self._where())]
        new = any(not os.path.exists(p) for p in changed)
        if not dry:
            for p in changed:
                _write(p, self.paths[p])
        return [Line("+" if new else "~", f"{self._where()}  {self.label}".rstrip())]

    def undo(self, dry: bool = False) -> List[Line]:
        gone = [p for p in self.paths if os.path.exists(p)]
        if not gone:
            return []
        if not dry:
            for p in gone:
                File(p, "").undo()
        return [Line("-", self._where())]

    def present(self) -> bool:
        return all(os.path.exists(p) for p in self.paths)

    def _where(self) -> str:
        names = sorted(os.path.basename(p) for p in self.paths)
        folder = _tilde(os.path.dirname(next(iter(self.paths))))
        stem = os.path.commonprefix(names)
        return f"{folder}{os.sep}{stem}*  ({len(names)} files)" if len(names) > 1 else f"{folder}{os.sep}{names[0]}"
