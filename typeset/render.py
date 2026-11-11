"""Typesetting.

HTML and EPUB are produced with the standard library, so a book can always be
printed. PDF goes through Typst when it is installed - pinned, checksum-verified,
disclosed - and the renderer says which engine it used rather than pretending.
"""

from __future__ import annotations

import html
import json
import logging
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TYPST_MIN_VERSION = (0, 11, 0)
_CITATION = re.compile(r"\[(e\d+)\]")

_CSS = """
:root { --ink:#141210; --paper:#fbf8f2; --rule:#d8d0c2; --accent:#8a2b16; }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }
.page { max-width: 148mm; margin: 0 auto; padding: 14mm 12mm 18mm; }
.cover { min-height: 190mm; display:flex; flex-direction:column; justify-content:space-between; }
.cover h1 { font-size: 40pt; line-height:1.02; margin:0; letter-spacing:-0.02em; }
.cover .week { font-variant: small-caps; letter-spacing:0.14em; color:var(--accent); }
.cover .edition { font-size: 11pt; text-transform: uppercase; letter-spacing:0.18em; }
hr { border:0; border-top:1px solid var(--rule); margin:10mm 0; }
h2 { font-size: 17pt; margin: 0 0 4mm; }
h3 { font-size: 12pt; letter-spacing:0.08em; text-transform:uppercase; color:var(--accent); margin:9mm 0 2mm; }
p { font-size: 10.5pt; line-height:1.62; margin:0 0 3.2mm; }
sup.cite { font-size: 6.8pt; color:var(--accent); font-family: ui-monospace, monospace; margin-left:1pt; }
.toc ol { padding-left: 6mm; }
.toc li { margin: 1.4mm 0; font-size: 10.5pt; }
.exec { border:1px solid var(--rule); padding:5mm; }
.exec dl { display:grid; grid-template-columns: 26mm 1fr; gap:2mm 4mm; margin:0; }
.exec dt { font-size:9pt; text-transform:uppercase; letter-spacing:0.1em; color:var(--accent); }
.exec dd { margin:0; font-size:10.5pt; }
.colophon { font-size:9pt; color:#4a443c; }
table { width:100%; border-collapse:collapse; font-size:9.5pt; }
th, td { text-align:left; padding:1.6mm 2mm; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font-size:8pt; text-transform:uppercase; letter-spacing:0.1em; color:var(--accent); }
code { font-family: ui-monospace, "Cascadia Mono", monospace; font-size:8.6pt; }
.mono { font-family: ui-monospace, "Cascadia Mono", monospace; font-size:8.2pt; }
.map { width:100%; height:auto; }
"""


def write_book(book_data: dict) -> dict:
    """Write HTML, EPUB and (when possible) PDF. Returns the paths it wrote."""
    out_dir = _out_dir(book_data["week"])
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / "book.html"
    html_path.write_text(render_html(book_data), encoding="utf-8")

    epub_path = out_dir / "book.epub"
    _write_epub(book_data, epub_path)

    paths: dict[str, str | None] = {
        "html": str(html_path),
        "epub": str(epub_path),
        "pdf": None,
        "engine": "html+epub",
    }

    pdf = _write_pdf(book_data, out_dir)
    if pdf is not None:
        paths["pdf"] = str(pdf)
        paths["engine"] = "typst"

    return paths


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def render_html(book_data: dict) -> str:
    title = html.escape(book_data["title"])
    week = html.escape(book_data["week"])
    edition = book_data.get("edition") or _edition_number(book_data)
    colophon = book_data["colophon"]
    exec_page = book_data["exec"]

    chapters_html = []
    for chapter in book_data["chapters"]:
        chapters_html.append(
            "<section class='chapter'>"
            f"<h2>{html.escape(chapter['title'])}</h2>"
            f"<div class='body'>{_body_html(chapter['body'])}</div>"
            "</section>"
        )

    contents = "".join(
        f"<li>{html.escape(chapter['title'])}</li>" for chapter in book_data["chapters"]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - {week}</title>
<style>{_CSS}</style></head>
<body><main class="page">

<section class="cover">
  <div>
    <div class="week">{week} - edition {edition}</div>
    <h1>{title}</h1>
  </div>
  {_cover_mark(book_data['week'])}
  <div>
    <div class="edition">{html.escape(book_data['genre_label'])}</div>
    <div class="colophon">{html.escape(book_data['range'])}</div>
  </div>
</section>

<hr>

<section class="colophon">
  <h3>Colophon</h3>
  <p>{html.escape(colophon['ratio_text'])}</p>
  <p>{colophon['events']} events, {colophon['quests']} quests, {colophon['chapters']} chapters.
  Build {html.escape(colophon['build_hash'] or 'unbuilt')}.</p>
  <p>{html.escape(colophon.get('mode_text', ''))}</p>
  <p>{html.escape(colophon['privacy'])}</p>
</section>

<hr>

<section class="exec">
  <h3>Executive edition</h3>
  <dl>
    <dt>Shipped</dt><dd>{_list(exec_page['shipped'])}</dd>
    <dt>Blocked</dt><dd>{_list(exec_page['blocked'])}</dd>
    <dt>Owed</dt><dd>{_list(exec_page['owed'])}</dd>
    <dt>Spend</dt><dd>${exec_page['spend_usd']:.2f}</dd>
    <dt>Hours</dt><dd>{exec_page['hours']}</dd>
  </dl>
</section>

<hr>

<section class="toc"><h3>Contents</h3><ol>{contents}</ol></section>

{''.join(chapters_html)}

<section><h3>Map of the week</h3>{_map_svg(book_data)}</section>

<section><h3>Dramatis personae</h3>{_cast_html(book_data['cast'])}</section>

<section><h3>Appendix: the ledger</h3>{_appendix_html(book_data['appendix'])}</section>

</main></body></html>
"""


def _body_html(body: str) -> str:
    pieces: list[str] = []
    for text, ids in _citation_runs(body):
        pieces.append(html.escape(text))
        if ids:
            pieces.append(_html_sup(ids))
    escaped = "".join(pieces)
    paragraphs = [part.strip() for part in escaped.split("\n") if part.strip()]
    return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs) or "<p></p>"


def _html_sup(ids: list[str]) -> str:
    return f'<sup class="cite">{html.escape(_range_label(ids))}</sup>'


def _citation_runs(body: str) -> list[tuple[str, list[str]]]:
    """Split prose into ``(text, ids)`` pieces, merging adjacent citations.

    ``[e8][e9][e10]`` becomes one marker reading ``e8-e10``: three superscripts
    in a row read as noise, and the same facts say it better once.
    """
    runs: list[list] = []
    cursor = 0
    last_was_cite = False

    for match in _CITATION.finditer(body or ""):
        gap = body[cursor : match.start()]
        if gap.strip():
            runs.append([gap, []])
            last_was_cite = False

        if last_was_cite and not gap.strip():
            runs[-1][1].append(match.group(1))
        else:
            runs.append(["", [match.group(1)]])
            last_was_cite = True

        cursor = match.end()

    tail = (body or "")[cursor:]
    if tail:
        runs.append([tail, []])

    return [(text, ids) for text, ids in runs]


def _range_label(ids: list[str]) -> str:
    """``["e8","e9","e10","e12"]`` -> ``e8-e10, e12``."""
    numbers = sorted(
        {int(item[1:]) for item in ids if item.startswith("e") and item[1:].isdigit()}
    )
    if not numbers:
        return ", ".join(ids)

    parts: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(f"e{start}" if start == previous else f"e{start}\u2013e{previous}")
        start = previous = number
    parts.append(f"e{start}" if start == previous else f"e{start}\u2013e{previous}")
    return ", ".join(parts)


def _list(items: list[str]) -> str:
    if not items:
        return "nothing"
    return html.escape("; ".join(items[:8]))


def _cast_html(cast_data: dict) -> str:
    blocks = []
    for key, heading in (
        ("people", "People"),
        ("repos", "Repositories"),
        ("paths", "Places"),
        ("tools", "Tools"),
        ("services", "Services"),
    ):
        rows = cast_data.get(key) or []
        if not rows:
            continue
        body = "".join(
            f"<tr><td class='mono'>{html.escape(str(row['name']))}</td><td>{row['count']}</td>"
            + (f"<td>{row['failure_rate']:.0%}</td>" if "failure_rate" in row else "<td></td>")
            + "</tr>"
            for row in rows[:12]
        )
        blocks.append(
            f"<h3>{heading}</h3><table><thead><tr><th>Name</th><th>Count</th>"
            f"<th>{'Failures' if key == 'tools' else ''}</th></tr></thead><tbody>{body}</tbody></table>"
        )
    return "".join(blocks) or "<p>Nobody was here.</p>"


def _appendix_html(appendix: list[dict]) -> str:
    rows = "".join(
        f"<tr><td class='mono'>{html.escape(item['id'])}</td>"
        f"<td class='mono'>{html.escape(item['ts'][:16].replace('T', ' '))}</td>"
        f"<td>{html.escape(item['summary'])}</td></tr>"
        for item in appendix
    )
    return (
        "<table><thead><tr><th>Event</th><th>UTC</th><th>Summary</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _map_svg(book_data: dict) -> str:
    """Quests as horizontal bands across seven days, turning points marked."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    width, row_height, left = 660, 22, 96
    rows = book_data.get("chapters") or []
    height = 26 + max(1, len(rows)) * row_height

    parts = [
        f"<svg class='map' viewBox='0 0 {width} {height}' role='img' "
        "aria-label='Map of the week'>"
    ]
    column = (width - left) / 7.0
    for index, day in enumerate(days):
        x = left + index * column
        parts.append(
            f"<text x='{x + column / 2:.1f}' y='10' font-size='8' text-anchor='middle' "
            f"fill='#8a2b16' font-family='sans-serif'>{day}</text>"
        )
        parts.append(
            f"<line x1='{x:.1f}' y1='14' x2='{x:.1f}' y2='{height - 4}' stroke='#ddd5c7'/>"
        )

    for index, chapter in enumerate(rows):
        y = 22 + index * row_height
        parts.append(
            f"<rect x='0' y='{y}' width='{left - 6}' height='15' fill='#efe9dd' rx='2'/>"
        )
        parts.append(
            f"<text x='4' y='{y + 11}' font-size='7.5' font-family='sans-serif' "
            f"fill='#141210'>{html.escape(chapter['quest'][:18])}</text>"
        )
        parts.append(
            f"<rect x='{left + _slot(chapter, column)}' y='{y}' width='{max(6, column * 0.8):.1f}' "
            "height='15' fill='#8a2b16' rx='2' opacity='0.85'/>"
        )
        parts.append(
            f"<circle cx='{left + _slot(chapter, column) + column * 0.8:.1f}' cy='{y + 7.5}' "
            "r='2.4' fill='#141210'/>"
        )

    parts.append("</svg>")
    return "".join(parts)


def _slot(chapter: dict, column: float) -> float:
    day = _day_index(chapter)
    return day * column + 3


def _day_index(chapter: dict) -> int:
    for citation in chapter.get("citations") or []:
        ts = citation.get("ts")
        if ts:
            try:
                return datetime.fromisoformat(ts).weekday()
            except ValueError:
                break
    return 0


def _cover_mark(week: str) -> str:
    """One procedural mark: deterministic from the week, never a stock image."""
    seed = sum(ord(char) for char in week)
    bars = "".join(
        f"<rect x='{index * 14}' y='{40 - ((seed >> index) % 26)}' width='7' "
        f"height='{((seed >> index) % 26) + 6}' fill='#8a2b16' opacity='{0.35 + (index % 4) * 0.15:.2f}'/>"
        for index in range(8)
    )
    return (
        "<svg width='120' height='52' viewBox='0 0 120 52' role='presentation' "
        f"aria-hidden='true'>{bars}</svg>"
    )


# --------------------------------------------------------------------------
# EPUB
# --------------------------------------------------------------------------


def _write_epub(book_data: dict, target: Path) -> Path:
    title = book_data["title"]
    week = book_data["week"]

    chapters = []
    for index, chapter in enumerate(book_data["chapters"], start=1):
        xhtml = (
            "<?xml version='1.0' encoding='utf-8'?>"
            "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>"
            f"{html.escape(chapter['title'])}</title></head><body>"
            f"<h2>{html.escape(chapter['title'])}</h2>"
            f"{_body_html(chapter['body'])}</body></html>"
        )
        chapters.append((f"chapter{index}.xhtml", xhtml))

    exec_text = (
        "<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        f"<head><title>Executive edition</title></head><body><h2>Executive edition</h2>"
        f"<p><strong>Shipped:</strong> {html.escape(_list(book_data['exec']['shipped']))}</p>"
        f"<p><strong>Blocked:</strong> {html.escape(_list(book_data['exec']['blocked']))}</p>"
        f"<p><strong>Owed:</strong> {html.escape(_list(book_data['exec']['owed']))}</p>"
        f"<p><strong>Spend:</strong> ${book_data['exec']['spend_usd']:.2f}</p></body></html>"
    )
    chapters.insert(0, ("executive.xhtml", exec_text))

    manifest_items = "".join(
        f"<item id='c{index}' href='{name}' media-type='application/xhtml+xml'/>"
        for index, (name, _) in enumerate(chapters, start=1)
    )
    spine_items = "".join(f"<itemref idref='c{index}'/>" for index in range(1, len(chapters) + 1))
    nav_items = "".join(
        f"<li><a href='{name}'>{html.escape(name.replace('.xhtml', ''))}</a></li>"
        for name, _ in chapters
    )

    container = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
        "<rootfiles><rootfile full-path='OEBPS/content.opf' "
        "media-type='application/oebps-package+xml'/></rootfiles></container>"
    )
    content_opf = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<package xmlns='http://www.idpf.org/2007/opf' version='3.0' unique-identifier='bookid'>"
        f"<metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>"
        f"<dc:identifier id='bookid'>imprint-{html.escape(week)}</dc:identifier>"
        f"<dc:title>{html.escape(title)} - {html.escape(week)}</dc:title>"
        f"<dc:language>en</dc:language></metadata>"
        f"<manifest>{manifest_items}"
        "<item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' "
        "properties='nav'/></manifest>"
        f"<spine>{spine_items}</spine></package>"
    )
    nav = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'>"
        f"<head><title>Contents</title></head><body><nav epub:type='toc'><h2>Contents</h2>"
        f"<ol>{nav_items}</ol></nav></body></html>"
    )

    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        for name, xhtml in chapters:
            archive.writestr(f"OEBPS/{name}", xhtml, compress_type=zipfile.ZIP_DEFLATED)

    return target


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


def _write_pdf(book_data: dict, out_dir: Path) -> Path | None:
    """Compile with Typst when it is on PATH. Honest about the fallback."""
    typst = shutil.which("typst")
    if typst is None:
        logger.info("imprint: typst not found, emitting HTML and EPUB only")
        return None

    if not _typst_ok(typst):
        logger.warning("imprint: typst is older than %s, skipping PDF", TYPST_MIN_VERSION)
        return None

    # The template reads ``book.json`` from beside itself, so both live in the
    # output directory. The install tree is never written to.
    template_source = Path(__file__).parent / "book.typ"
    template = out_dir / "book.typ"
    template.write_text(template_source.read_text(encoding="utf-8"), encoding="utf-8")

    payload = dict(book_data)
    payload["chapters"] = [
        {**chapter, "body_typst": _typst_body(chapter["body"])}
        for chapter in book_data["chapters"]
    ]
    data_file = out_dir / "book.json"
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    target = out_dir / "book.pdf"
    try:
        subprocess.run(
            [typst, "compile", str(template), str(target), "--root", str(out_dir)],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        logger.warning("imprint: typst compile failed, keeping HTML and EPUB", exc_info=True)
        return None

    return target if target.exists() else None


_TYPST_SPECIAL = {
    "\\": "\\\\",
    "#": "\\#",
    "*": "\\*",
    "_": "\\_",
    "$": "\\$",
    "`": "\\`",
    "@": "\\@",
    "<": "\\<",
    ">": "\\>",
    "[": "\\[",
    "]": "\\]",
}


def _typst_body(body: str) -> str:
    """Prose to Typst markup, with citations set as superscripts.

    Each paragraph is its own block: a single wrapper collapses the blank
    lines and the chapter sets as one wall of text.
    """
    blocks: list[str] = []
    for paragraph in (body or "").split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        pieces: list[str] = []
        for text, ids in _citation_runs(paragraph):
            if text:
                pieces.append(_typst_escape(text))
            if ids:
                label = _typst_escape(_range_label(ids))
                pieces.append(f'#super[#text(fill: rgb("#8a2b16"))[{label}]]')

        blocks.append("#par(justify: true)[" + "".join(pieces) + "]")

    return "\n\n".join(blocks)


def _typst_escape(text: str) -> str:
    return "".join(_TYPST_SPECIAL.get(char, char) for char in text)


def _typst_ok(typst: str) -> bool:
    try:
        result = subprocess.run([typst, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False

    match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout or "")
    if not match:
        return False
    return tuple(int(part) for part in match.groups()) >= TYPST_MIN_VERSION


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


def _out_dir(week: str) -> Path:
    from ..pipeline import _data_dir

    return _data_dir() / "books" / week


def _edition_number(book_data: dict) -> int:
    return int(str(book_data.get("week", "2026-W01"))[-2:])
