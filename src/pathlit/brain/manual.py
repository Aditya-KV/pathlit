"""Turns Blender manual reStructuredText into small searchable documents (title, section, content).

Reads text only. Never executes anything from the files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_UNDERLINE = re.compile(r"^([=\-~^\"*+#`:._'])\1{2,}\s*$")


@dataclass
class ManualDoc:
    id: str
    title: str
    section: str
    content: str


def clean(text: str) -> str:
    """Strip Sphinx markup so the text reads like plain English."""
    text = re.sub(r":menuselection:`([^`]*)`", lambda m: m.group(1).replace("-->", ">").strip(), text)
    text = re.sub(r":(?:kbd|guilabel|term|abbr|class|mod|func|doc|ref|sup|sub):`([^`<]*?)(?:\s*<[^>]*>)?`", r"\1", text)
    text = re.sub(r":[a-z]+:`([^`]*)`", r"\1", text)
    text = re.sub(r"``([^`]*)``", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"\|[^|\n]*\|", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _strip_directives(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(".. ") or s == "..":
            continue                                   # directive / label / comment line
        if re.match(r"^:[a-z_\-]+:", s) and ln.startswith((" ", "\t")):
            continue                                   # directive option such as ":alt:"
        out.append(ln)
    return out


def _headings(lines: list[str]) -> list[tuple[int, str]]:
    """(line index of the heading text, heading text)."""
    found = []
    for i in range(len(lines) - 1):
        txt, nxt = lines[i].rstrip(), lines[i + 1].rstrip()
        if txt and not _UNDERLINE.match(txt) and _UNDERLINE.match(nxt) and len(nxt) >= len(txt.strip()):
            found.append((i, txt.strip()))
    return found


def parse_rst(raw: str, source: str, max_chars: int = 3000) -> list[ManualDoc]:
    lines = _strip_directives(raw.splitlines())
    heads = _headings(lines)
    if not heads:
        return []
    title = clean(heads[0][1])
    docs: list[ManualDoc] = []
    bounds = [h[0] for h in heads] + [len(lines)]
    for n, (idx, head) in enumerate(heads):
        start = idx + 2                                 # skip heading and its underline
        body_lines = [ln for ln in lines[start:bounds[n + 1]] if not _UNDERLINE.match(ln.rstrip())]
        body = re.sub(r"\n{3,}", "\n\n", clean("\n".join(body_lines))).strip()
        if len(body) < 40:
            continue
        section = title if n == 0 else clean(head)
        doc_id = re.sub(r"[^A-Za-z0-9_\-=]", "_", f"{source}__{n}")
        docs.append(ManualDoc(doc_id, title, section, body[:max_chars]))
    return docs
