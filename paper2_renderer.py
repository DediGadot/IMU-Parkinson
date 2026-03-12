"""
Structured HTML renderer for the replacement academic manuscript pipeline.

The goal is to make figure/table numbering and asset handling explicit so the
generator fails loudly instead of silently drifting.
"""
from __future__ import annotations

import base64
import html
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path


PLACEHOLDER_TOKENS = (
    "[Authors]",
    "[Affiliations]",
    "[email]",
    "[repository URL]",
    "TODO",
    "TBD",
)


@dataclass(frozen=True)
class FigureRef:
    number: int
    html_id: str
    filename: str

    @property
    def label(self) -> str:
        return f"Figure {self.number}"


@dataclass(frozen=True)
class TableRef:
    number: int
    html_id: str

    @property
    def label(self) -> str:
        return f"Table {self.number}"


def _embed_image(path: Path) -> tuple[str, str]:
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return mime_type, encoded


class PaperBuilder:
    def __init__(self, root: Path, page_title: str) -> None:
        self.root = root
        self.fig_dir = root / "figures"
        self.page_title = page_title
        self._parts: list[str] = []
        self._figure_count = 0
        self._table_count = 0

    def add_raw(self, raw_html: str) -> None:
        self._parts.append(raw_html)

    def add_title_block(
        self,
        title: str,
        authors: str,
        affiliations: str,
        correspondence: str,
    ) -> None:
        self._parts.append(
            f"""
<div class="title-block">
  <h1>{title}</h1>
  <p class="authors">{authors}</p>
  <p class="affiliations">{affiliations}</p>
  <p class="correspondence">{correspondence}</p>
</div>
""".strip()
        )

    def add_abstract(self, paragraphs: list[str], keywords: str) -> None:
        body = "\n".join(f"  <p>{paragraph}</p>" for paragraph in paragraphs)
        self._parts.append(
            f"""
<div class="abstract">
  <h2>Abstract</h2>
{body}
  <p class="keywords"><strong>Keywords:</strong> {keywords}</p>
</div>
""".strip()
        )

    def add_toc(self, items: list[tuple[str, str]]) -> None:
        entries = "\n".join(
            f'    <li><a href="#{html.escape(anchor)}">{html.escape(label)}</a></li>'
            for anchor, label in items
        )
        self._parts.append(
            f"""
<div class="toc">
  <h3>Contents</h3>
  <ol>
{entries}
  </ol>
</div>
""".strip()
        )

    def section(self, title: str, anchor: str) -> None:
        self._parts.append(f'<h2 id="{html.escape(anchor)}">{title}</h2>')

    def subsection(self, title: str, anchor: str | None = None) -> None:
        if anchor:
            self._parts.append(f'<h3 id="{html.escape(anchor)}">{title}</h3>')
        else:
            self._parts.append(f"<h3>{title}</h3>")

    def subsubsection(self, title: str) -> None:
        self._parts.append(f"<h4>{title}</h4>")

    def paragraph(self, body_html: str, css_class: str | None = None) -> None:
        if css_class:
            self._parts.append(f'<p class="{html.escape(css_class)}">{body_html}</p>')
        else:
            self._parts.append(f"<p>{body_html}</p>")

    def ordered_list(self, items: list[str]) -> None:
        rows = "\n".join(f"  <li>{item}</li>" for item in items)
        self._parts.append(f"<ol>\n{rows}\n</ol>")

    def unordered_list(self, items: list[str]) -> None:
        rows = "\n".join(f"  <li>{item}</li>" for item in items)
        self._parts.append(f"<ul>\n{rows}\n</ul>")

    def add_figure(self, filename: str, caption: str, alt_text: str | None = None) -> FigureRef:
        path = self.fig_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Required figure asset is missing: {path}")

        self._figure_count += 1
        ref = FigureRef(
            number=self._figure_count,
            html_id=f"figure-{self._figure_count}",
            filename=filename,
        )
        mime_type, encoded = _embed_image(path)
        alt_text = alt_text or caption
        self._parts.append(
            f"""
<figure id="{ref.html_id}">
  <img src="data:{mime_type};base64,{encoded}" alt="{html.escape(alt_text)}" style="max-width:100%;height:auto;">
  <figcaption><strong>Figure {ref.number}.</strong> {html.escape(caption)}</figcaption>
</figure>
""".strip()
        )
        return ref

    def add_table(
        self,
        caption: str,
        headers: list[str],
        rows: list[list[str]],
        row_classes: list[str | None] | None = None,
        note: str | None = None,
    ) -> TableRef:
        if not rows:
            raise ValueError(f"Table '{caption}' has no rows")

        self._table_count += 1
        ref = TableRef(number=self._table_count, html_id=f"table-{self._table_count}")
        header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)

        row_classes = row_classes or [None] * len(rows)
        if len(row_classes) != len(rows):
            raise ValueError(f"Table '{caption}' row_classes length mismatch")

        body_rows: list[str] = []
        for row, row_class in zip(rows, row_classes):
            class_attr = f' class="{html.escape(row_class)}"' if row_class else ""
            cells = "".join(f"<td>{cell}</td>" for cell in row)
            body_rows.append(f"    <tr{class_attr}>{cells}</tr>")

        note_html = f'<p class="table-note">{html.escape(note)}</p>' if note else ""
        self._parts.append(
            f"""
<table id="{ref.html_id}">
  <caption><strong>Table {ref.number}.</strong> {html.escape(caption)}</caption>
  <thead>
    <tr>{header_html}</tr>
  </thead>
  <tbody>
{chr(10).join(body_rows)}
  </tbody>
</table>
{note_html}
""".strip()
        )
        return ref

    def add_references(self, entries: list[str], anchor: str = "refs") -> None:
        refs = "\n".join(f"  <p>{entry}</p>" for entry in entries)
        self._parts.append(
            f"""
<h2 id="{html.escape(anchor)}">References</h2>
<div class="references">
{refs}
</div>
""".strip()
        )

    def render(self) -> str:
        body = "\n\n".join(self._parts)
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(self.page_title)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,wght@0,400;0,600;0,700;1,400&family=Source+Sans+3:wght@400;600;700&display=swap');

  :root {{
    --text: #1c1c1c;
    --bg: #ffffff;
    --accent: #124a6d;
    --accent-soft: #eaf3f8;
    --border: #d9dde3;
    --header: #22384a;
    --table-alt: #f7f9fb;
    --best: #e6f4ea;
    --highlight: #fff8dc;
    --muted: #5f6b76;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0 auto;
    max-width: 980px;
    padding: 36px 28px 80px;
    color: var(--text);
    background: var(--bg);
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 16px;
    line-height: 1.7;
  }}

  .title-block {{
    text-align: center;
    padding-bottom: 28px;
    margin-bottom: 32px;
    border-bottom: 2px solid var(--accent);
  }}

  .title-block h1 {{
    margin: 0 0 18px;
    font-family: 'Source Sans 3', Helvetica, sans-serif;
    font-size: 1.9rem;
    line-height: 1.25;
    color: var(--accent);
  }}

  .authors, .affiliations, .correspondence {{
    margin: 4px 0;
    font-family: 'Source Sans 3', Helvetica, sans-serif;
  }}

  .affiliations, .correspondence {{
    color: var(--muted);
    font-size: 0.94rem;
  }}

  .abstract {{
    margin: 30px 0;
    padding: 22px 26px;
    border-left: 4px solid var(--accent);
    background: var(--accent-soft);
    border-radius: 0 6px 6px 0;
  }}

  .abstract h2 {{
    margin-top: 0;
    border: 0;
    padding: 0;
    font-size: 1.1rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  .keywords {{
    margin-top: 14px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
    font-size: 0.92rem;
  }}

  .toc {{
    margin: 28px 0 36px;
    padding: 18px 22px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: #fcfdff;
    font-family: 'Source Sans 3', Helvetica, sans-serif;
  }}

  .toc h3 {{
    margin-top: 0;
  }}

  h2, h3, h4 {{
    font-family: 'Source Sans 3', Helvetica, sans-serif;
    color: var(--accent);
  }}

  h2 {{
    margin: 40px 0 14px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    font-size: 1.38rem;
  }}

  h3 {{
    margin: 26px 0 10px;
    font-size: 1.08rem;
  }}

  h4 {{
    margin: 18px 0 8px;
    font-size: 0.96rem;
    font-style: italic;
    color: #334e63;
  }}

  p {{
    margin: 0 0 12px;
    text-align: justify;
    hyphens: auto;
  }}

  ol, ul {{
    margin: 10px 0 14px 24px;
  }}

  li {{
    margin: 4px 0;
  }}

  figure {{
    margin: 28px 0;
    text-align: center;
  }}

  figcaption {{
    margin-top: 10px;
    font-size: 0.94rem;
    text-align: left;
    color: #27343f;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0 8px;
    font-family: 'Source Sans 3', Helvetica, sans-serif;
    font-size: 0.92rem;
  }}

  caption {{
    margin-bottom: 8px;
    text-align: left;
    font-size: 0.97rem;
    font-weight: 600;
  }}

  th {{
    background: var(--header);
    color: white;
    text-align: left;
    padding: 10px 12px;
  }}

  td {{
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}

  tbody tr:nth-child(even) td {{
    background: var(--table-alt);
  }}

  tbody tr.best td {{
    background: var(--best);
    font-weight: 700;
  }}

  tbody tr.highlight td {{
    background: var(--highlight);
  }}

  .table-note {{
    margin-top: 0;
    color: var(--muted);
    font-size: 0.88rem;
    font-family: 'Source Sans 3', Helvetica, sans-serif;
  }}

  .references p {{
    margin-bottom: 10px;
    text-align: left;
    font-size: 0.94rem;
  }}

  a {{
    color: var(--accent);
    text-decoration: none;
  }}

  a:hover {{
    text-decoration: underline;
  }}

  @media (max-width: 700px) {{
    body {{
      padding: 24px 16px 56px;
      font-size: 15px;
    }}

    table {{
      font-size: 0.84rem;
    }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""
        self._validate(page)
        return page

    def _validate(self, page: str) -> None:
        text_only = re.sub(r"data:[^;]+;base64,[A-Za-z0-9+/=]+", "", page)
        for token in PLACEHOLDER_TOKENS:
            if token in text_only:
                raise ValueError(f"Placeholder token leaked into output: {token}")

        figure_numbers = re.findall(r"<figcaption><strong>Figure (\d+)\.</strong>", page)
        expected_figures = [str(i) for i in range(1, self._figure_count + 1)]
        if figure_numbers != expected_figures:
            raise ValueError(
                f"Figure numbering mismatch: expected {expected_figures}, got {figure_numbers}"
            )

        table_numbers = re.findall(r"<caption><strong>Table (\d+)\.</strong>", page)
        expected_tables = [str(i) for i in range(1, self._table_count + 1)]
        if table_numbers != expected_tables:
            raise ValueError(
                f"Table numbering mismatch: expected {expected_tables}, got {table_numbers}"
            )

        ids = re.findall(r'id="([^"]+)"', page)
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate HTML ids detected in generated paper")
