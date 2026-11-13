"""Chuyển Markdown đơn giản (do AI hoặc giáo viên viết) sang HTML an toàn.

Hỗ trợ: đoạn văn, xuống dòng, **đậm**, *nghiêng*, `mã`, khối ```mã```, danh sách - / 1.
Mọi nội dung đều được escape trước nên không chèn được thẻ HTML.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.DOTALL)
_BULLET = re.compile(r"^\s*[-*•]\s+")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+")


def _inline(text: str) -> str:
    text = str(escape(text))
    codes: list[str] = []

    def keep_code(match: re.Match) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", keep_code, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
    return text


def render_md(source: str | None) -> Markup:
    source = (source or "").replace("\r\n", "\n").strip()
    if not source:
        return Markup("")
    blocks: list[str] = []
    pos = 0
    for match in _FENCE.finditer(source):
        blocks.extend(_render_text(source[pos : match.start()]))
        blocks.append(f"<pre class=\"code-block\"><code>{escape(match.group(1).rstrip())}</code></pre>")
        pos = match.end()
    blocks.extend(_render_text(source[pos:]))
    return Markup("\n".join(b for b in blocks if b))


def _render_text(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.rstrip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        if all(_BULLET.match(ln) for ln in lines):
            items = "".join("<li>" + _inline(_BULLET.sub("", ln)) + "</li>" for ln in lines)
            out.append(f"<ul>{items}</ul>")
        elif all(_NUMBERED.match(ln) for ln in lines):
            items = "".join("<li>" + _inline(_NUMBERED.sub("", ln)) + "</li>" for ln in lines)
            out.append(f"<ol>{items}</ol>")
        else:
            out.append("<p>" + "<br>".join(_inline(ln) for ln in lines) + "</p>")
    return out
