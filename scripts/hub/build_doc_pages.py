#!/usr/bin/env python3
"""Turn the main repo docs into pages for the Omiryn hub.

The hub (the build map artifact) links each part to its docs. A doc that lives only in the repo
cannot be opened from there, so this script makes one HTML page per doc, in the hub's own look, for
publishing as an artifact. The repo file stays the source: a page is a dated copy, and says so.

    python scripts/hub/build_doc_pages.py --out /path/to/folder

Then publish each file (the same file path, or its page's url, updates the page in place).
No dependencies: the Markdown the docs use (headings, lists, tables, code, quotes) is read here.
"""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HUB_URL = "https://claude.ai/artifact/RHbCH4by15ApJQXETMd3zE"
# A table cell longer than this is prose: its table is shown as entries, one per row.
LONG_CELL = 280


@dataclass(frozen=True)
class Doc:
    slug: str
    source: str
    title: str
    about: str


DOCS = (
    Doc("matching-design", "docs/matching-design.md", "Omiryn Matching Design", "The flow, the algorithm and every test result."),
    Doc("ability-questions", "docs/ability-questions.md", "Omiryn Ability Questions", "The 125 test questions, by area and life stage, with the rule for a right reply."),
    Doc("progress-log", "docs/progress.md", "Omiryn Progress Log", "Where the product stands and every change with its date."),
    Doc("security-checklist", "docs/production-security-checklist.md", "Omiryn Security Checklist", "What must be true before real users."),
    Doc("go-live-plan", "docs/production-plan.md", "Omiryn Go-Live Plan", "The plan to take Omiryn live."),
    Doc("deploy-notes", "docs/gcp-deployment.md", "Omiryn Deploy Notes", "How the server is deployed on Google Cloud."),
    Doc("api-contract", "docs/api-contract.md", "Omiryn API Contract", "What the apps send to the server and get back."),
    Doc("architecture-notes", "docs/architecture.md", "Omiryn Architecture Notes", "The system in words."),
)


# ---- inline text

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])")


def _link(match: re.Match[str]) -> str:
    label, target = match.group(1), html.unescape(match.group(2))
    if target.startswith("https://"):
        return f'<a href="{html.escape(target, quote=True)}" target="_blank" rel="noopener">{label}</a>'
    # A link to another repo file cannot open from a page: show where it points.
    return f'{label} <span class="path">({html.escape(target)})</span>'


def inline(text: str) -> str:
    out = []
    for index, piece in enumerate(re.split(r"`([^`]*)`", text)):
        if index % 2:
            out.append(f"<code>{html.escape(piece)}</code>")
            continue
        piece = html.escape(piece, quote=False)
        piece = re.sub(r"&lt;br\s*/?&gt;", "<br>", piece)
        piece = _LINK.sub(_link, piece)
        piece = _BOLD.sub(r"<strong>\1</strong>", piece)
        piece = _ITALIC.sub(r"<em>\1</em>", piece)
        out.append(piece)
    return "".join(out)


def plain(text: str) -> str:
    """Heading text without marks, for the contents list and ids."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = _LINK.sub(r"\1", text)
    return text.replace("**", "").replace("*", "").strip()


# ---- blocks

_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def cells(line: str) -> list[str]:
    """The cells of a table row; a | inside code or written \\| does not end a cell."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    out, current, in_code, index = [], [], False, 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            out.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    out.append("".join(current).strip())
    return out


class Page:
    def __init__(self) -> None:
        self.contents: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.has_entries = False

    def heading_id(self, text: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-")[:60] or "section"
        slug, count = base, 2
        while slug in self.ids:
            slug, count = f"{base}-{count}", count + 1
        self.ids.add(slug)
        return slug

    def blocks(self, lines: list[str], *, top: bool = True) -> str:
        out: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
            elif line.lstrip().startswith("```"):
                index = self._fence(lines, index, out)
            elif heading := _HEADING.match(line):
                level, text = len(heading.group(1)), heading.group(2)
                if level > 1 or not top:  # the page header already carries the title
                    anchor = self.heading_id(text)
                    if level == 2 and top:
                        self.contents.append((anchor, plain(text)))
                    tag = f"h{min(level, 4)}"
                    out.append(f'<{tag} id="{anchor}">{inline(text)}</{tag}>')
                index += 1
            elif re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", line):
                out.append("<hr>")
                index += 1
            elif line.lstrip().startswith("|") and index + 1 < len(lines) and _SEPARATOR.match(lines[index + 1]):
                index = self._table(lines, index, out)
            elif line.lstrip().startswith(">"):
                quoted = []
                while index < len(lines) and lines[index].lstrip().startswith(">"):
                    quoted.append(re.sub(r"^\s*>\s?", "", lines[index]))
                    index += 1
                out.append(f"<blockquote>{self.blocks(quoted, top=False)}</blockquote>")
            elif _ITEM.match(line):
                index = self._list(lines, index, out)
            else:
                para = []
                while index < len(lines) and lines[index].strip() and not self._starts_block(lines, index):
                    para.append(lines[index].strip())
                    index += 1
                out.append(f"<p>{inline(' '.join(para))}</p>")
        return "\n".join(out)

    @staticmethod
    def _starts_block(lines: list[str], index: int) -> bool:
        line = lines[index]
        return bool(
            line.lstrip().startswith(("```", ">"))
            or _HEADING.match(line)
            or _ITEM.match(line)
            or (line.lstrip().startswith("|") and index + 1 < len(lines) and _SEPARATOR.match(lines[index + 1]))
        )

    def _fence(self, lines: list[str], index: int, out: list[str]) -> int:
        language = lines[index].strip().strip("`").strip().lower()
        body = []
        index += 1
        while index < len(lines) and not lines[index].lstrip().startswith("```"):
            body.append(lines[index])
            index += 1
        text = html.escape("\n".join(body))
        if language == "mermaid":
            out.append(f'<div class="wide"><pre class="mermaid">{text}</pre></div>')
        else:
            out.append(f'<div class="wide"><pre><code>{text}</code></pre></div>')
        return index + 1

    def _table(self, lines: list[str], index: int, out: list[str]) -> int:
        head = cells(lines[index])
        index += 2
        rows = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            row = cells(lines[index])
            rows.append(row + [""] * (len(head) - len(row)))
            index += 1
        long_columns = [n for n in range(len(head)) if any(len(row[n]) > LONG_CELL for row in rows if n < len(row))]
        if long_columns:
            self.has_entries = True
            out.append(self._entries(head, rows, long_columns))
        else:
            body = "".join("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row[: len(head)]) + "</tr>" for row in rows)
            out.append(
                '<div class="wide"><table><thead><tr>'
                + "".join(f"<th>{inline(cell)}</th>" for cell in head)
                + f"</tr></thead><tbody>{body}</tbody></table></div>"
            )
        return index

    def _entries(self, head: list[str], rows: list[list[str]], long_columns: list[int]) -> str:
        """A table whose cells are paragraphs, one entry per row: short cells name it, long ones are its text."""
        short = [n for n in range(len(head)) if n not in long_columns]
        # A first column of row numbers ("7zp", "12") is the entry's tag; any other is part of its name.
        numbered = len(short) > 1 and all(len(row[short[0]]) <= 6 for row in rows)
        entries = []
        for row in rows:
            names = [row[n] for n in short if n < len(row) and row[n]]
            tag = names[0] if numbered and names else ""
            title = " · ".join(names[1:] if tag else names)
            body = "".join(
                (f'<p class="label">{inline(head[n])}</p>' if len(long_columns) > 1 and head[n] else "") + f"<p>{inline(row[n])}</p>"
                for n in long_columns
                if n < len(row) and row[n]
            )
            entries.append(
                '<article class="entry">'
                + (f'<span class="tag">{inline(tag)}</span>' if tag else "")
                + (f"<h4>{inline(title)}</h4>" if title else "")
                + body
                + "</article>"
            )
        return f'<div class="entries">{"".join(entries)}</div>'

    def _list(self, lines: list[str], index: int, out: list[str]) -> int:
        items: list[tuple[int, bool, str]] = []
        while index < len(lines):
            line = lines[index]
            if match := _ITEM.match(line):
                items.append((len(match.group(1).expandtabs(4)), match.group(2)[0].isdigit(), match.group(3)))
            elif line.strip() and line.startswith((" ", "\t")) and items:
                indent, ordered, text = items[-1]
                items[-1] = (indent, ordered, f"{text} {line.strip()}")
            elif not line.strip() and index + 1 < len(lines) and (_ITEM.match(lines[index + 1]) or lines[index + 1].startswith(("  ", "\t"))) and lines[index + 1].strip():
                pass  # an empty line inside the list
            else:
                break
            index += 1
        out.append(self._nested(items))
        return index

    def _nested(self, items: list[tuple[int, bool, str]]) -> str:
        if not items:
            return ""
        base, ordered = items[0][0], items[0][1]
        parts: list[str] = []
        position = 0
        while position < len(items):
            _, _, text = items[position]
            end = position + 1
            while end < len(items) and items[end][0] > base:
                end += 1
            parts.append(f"<li>{self._item(text)}{self._nested(items[position + 1 : end])}</li>")
            position = end
        tag = "ol" if ordered else "ul"
        return f"<{tag}>{''.join(parts)}</{tag}>"

    @staticmethod
    def _item(text: str) -> str:
        if box := re.match(r"\[( |x|X)\]\s+(.*)$", text):
            done = box.group(1) != " "
            state = "done" if done else "open"
            return f'<span class="box {state}" role="img" aria-label="{"Done" if done else "Not done"}"></span><span class="{"checked" if done else ""}">{inline(box.group(2))}</span>'
        return inline(text)


# ---- the page

STYLE = """
/* Layout: a document from the repo, in the build map's own look. A contents rail beside one reading
   column; tables scroll on their own; a table of long notes becomes a list of entries. */
:root {
  --paper: #f3eee4; --card: #fffdf8; --ink: #15120e; --muted: #6b6358; --line: #e2d9c9; --soft: #ebe4d6;
  --ember: #f8441f; --ember-text: #bc2e0f; --done: #2f8a4e;
  --font-display: "Fraunces", Georgia, "Times New Roman", serif;
  --font-ui: "Bricolage Grotesque", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-code: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #14110d; --card: #1e1a15; --ink: #f1ebdf; --muted: #a79e90; --line: #362f27; --soft: #28231c;
  --ember: #ff6b47; --ember-text: #ff8e70; --done: #57c27b; color-scheme: dark } }
:root[data-theme="dark"] {
  --paper: #14110d; --card: #1e1a15; --ink: #f1ebdf; --muted: #a79e90; --line: #362f27; --soft: #28231c;
  --ember: #ff6b47; --ember-text: #ff8e70; --done: #57c27b; color-scheme: dark }
* { box-sizing: border-box }
body { background: var(--paper); color: var(--ink); font-family: var(--font-ui); font-size: 16px; line-height: 1.6;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 72px }
.wrap { max-width: 1120px; margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px }
a { color: var(--ember-text); text-underline-offset: 3px }
:focus-visible { outline: 2px solid var(--ember); outline-offset: 2px }
.top { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; border-bottom: 1px solid var(--line); padding-bottom: 22px }
.eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600 }
h1, h2, h3, h4 { font-family: var(--font-display); font-weight: 600; text-wrap: balance; letter-spacing: -0.01em; margin: 0 }
h1 { font-size: clamp(30px, 5vw, 44px); line-height: 1.05; overflow-wrap: anywhere }
.lede { font-size: 18px; max-width: 62ch }
.meta { font-size: 13.5px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 16px }
.meta code { font-size: 12.5px }
.body { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 40px; align-items: start }
nav.contents { min-width: 0; position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); max-height: calc(100vh - 32px); overflow-y: auto; display: grid; gap: 8px; font-size: 14px }
nav.contents ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; border-left: 1px solid var(--line) }
nav.contents a { display: block; padding: 4px 0 4px 12px; color: var(--muted); text-decoration: none; margin-left: -1px; border-left: 1px solid transparent }
nav.contents a:hover { color: var(--ink); border-left-color: var(--ember) }
.filter { display: grid; gap: 6px; font-size: 13px; color: var(--muted) }
.filter input { font: inherit; color: var(--ink); background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; width: 100% }
.filter output { font-variant-numeric: tabular-nums }
main { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; max-width: 76ch }
main > h2 { font-size: 26px; margin-top: 26px; padding-top: 22px; border-top: 1px solid var(--line); scroll-margin-top: 16px }
main > h2:first-child { margin-top: 0; padding-top: 0; border-top: 0 }
main h3 { font-size: 20px; margin-top: 12px; scroll-margin-top: 16px }
main h4 { font-family: var(--font-ui); font-size: 16px; font-weight: 600; letter-spacing: 0 }
p { margin: 0 }
ul, ol { margin: 0; padding-left: 22px; display: grid; gap: 6px }
li > ul, li > ol { margin-top: 6px }
li:has(> .box) { list-style: none; margin-left: -22px; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px; align-items: start }
.box { width: 15px; height: 15px; border: 1.5px solid var(--muted); border-radius: 4px; margin-top: 5px }
.box.done { background: var(--done); border-color: var(--done) }
.checked { color: var(--muted) }
blockquote { margin: 0; padding: 4px 0 4px 16px; border-left: 2px solid var(--ember); font-family: var(--font-display); font-size: 18px; display: grid; gap: 8px }
hr { border: 0; border-top: 1px solid var(--line); width: 100%; margin: 8px 0 }
code { font-family: var(--font-code); font-size: 0.86em; background: var(--soft); padding: 1px 5px; border-radius: 4px; overflow-wrap: anywhere }
.path { color: var(--muted); font-size: 0.86em }
.wide { overflow-x: auto; max-width: 100% }
pre { margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; font-family: var(--font-code); font-size: 13.5px; line-height: 1.5; width: max-content; min-width: 100% }
pre code { background: transparent; padding: 0; font-size: inherit; overflow-wrap: normal }
table { border-collapse: collapse; font-size: 14.5px; min-width: 100%; font-variant-numeric: tabular-nums }
th, td { text-align: left; vertical-align: top; padding: 8px 14px 8px 0; border-bottom: 1px solid var(--line) }
th { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; white-space: nowrap }
td { min-width: 9ch }
.entries { display: grid; gap: 0; border-top: 1px solid var(--line) }
.entry { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 6px 14px; padding: 16px 0; border-bottom: 1px solid var(--line) }
.entry > * { grid-column: 2 }
.entry .tag { grid-column: 1; grid-row: 1 / span 9; font-family: var(--font-code); font-size: 13px; color: var(--ember-text); font-weight: 600; padding-top: 2px; overflow-wrap: anywhere }
.entry p { font-size: 15px }
.entry .label { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin-top: 4px }
.none { color: var(--muted) }
@media (max-width: 860px) {
  .body { grid-template-columns: minmax(0, 1fr); gap: 24px }
  nav.contents { position: static; max-height: none }
  .entry { grid-template-columns: 1fr } .entry > *, .entry .tag { grid-column: 1; grid-row: auto }
}
"""

FILTER_SCRIPT = """
<script>
(() => {
  const input = document.getElementById("entry-filter");
  const count = document.getElementById("entry-count");
  const entries = [...document.querySelectorAll(".entry")];
  if (!input || !entries.length) return;
  const texts = entries.map((entry) => entry.textContent.toLowerCase());
  const show = () => {
    const words = input.value.toLowerCase().split(/\\s+/).filter(Boolean);
    let shown = 0;
    entries.forEach((entry, i) => { const hit = words.every((w) => texts[i].includes(w)); entry.hidden = !hit; if (hit) shown++; });
    count.textContent = words.length ? `${shown} of ${entries.length} entries` : `${entries.length} entries`;
  };
  input.addEventListener("input", show);
  show();
})();
</script>
"""


def build(doc: Doc, today: date) -> str:
    text = (ROOT / doc.source).read_text(encoding="utf-8")
    page = Page()
    body = page.blocks(text.splitlines())
    contents = "".join(f'<li><a href="#{anchor}">{html.escape(title)}</a></li>' for anchor, title in page.contents)
    filter_box = (
        '<label class="filter" for="entry-filter">Find in the entries'
        '<input id="entry-filter" type="search" placeholder="A word, a date, a row number" autocomplete="off">'
        '<output id="entry-count" for="entry-filter"></output></label>'
        if page.has_entries
        else ""
    )
    copied = f"{today.day} {today.strftime('%B %Y')}"
    return f"""<title>{html.escape(doc.title)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  <header class="top">
    <span class="eyebrow">Omiryn · a doc from the repo</span>
    <h1>{html.escape(doc.title.removeprefix("Omiryn "))}</h1>
    <p class="lede">{html.escape(doc.about)}</p>
    <p class="meta"><span>Copied on {copied} from <code>{html.escape(doc.source)}</code>. The file in the repo is the source.</span><a href="{HUB_URL}" target="_blank" rel="noopener">Back to the build map</a></p>
  </header>
  <div class="body">
    <nav class="contents" aria-label="Contents">
      <span class="eyebrow">On this page</span>
      {f"<ol>{contents}</ol>" if contents else '<p class="none">One section.</p>'}
      {filter_box}
    </nav>
    <main>
{body}
    </main>
  </div>
</div>
{FILTER_SCRIPT if page.has_entries else ""}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Folder to write the pages into.")
    parser.add_argument("--only", action="append", help="Only these page names (see DOCS).")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for doc in DOCS:
        if args.only and doc.slug not in args.only:
            continue
        path = out / f"{doc.slug}.html"
        path.write_text(build(doc, date.today()), encoding="utf-8")
        print(f"{doc.slug}: {path} ({path.stat().st_size // 1024} KB) from {doc.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
