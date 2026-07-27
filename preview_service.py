from __future__ import annotations

from dataclasses import dataclass
import gc
from hashlib import sha256
from html import escape
import os
from pathlib import Path
import subprocess
import threading
from typing import Iterable, Iterator

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter


PREVIEW_RENDERER_VERSION = "3"
_NATIVE_RENDER_LOCK = threading.Lock()


@dataclass(frozen=True)
class PreviewResult:
    pdf_path: Path
    page_count: int


def default_preview_cache_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "DocSwift" / "preview-cache"


def _iter_blocks(parent: DocumentObject | _Cell) -> Iterator[Paragraph | Table]:
    if isinstance(parent, DocumentObject):
        parent_element = parent.element.body
    else:
        parent_element = parent._tc

    for child in parent_element.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def _paragraph_has_page_break(paragraph: Paragraph) -> bool:
    xml = paragraph._p.xml
    return (
        'w:type="page"' in xml
        or "<w:lastRenderedPageBreak" in xml
        or "w:lastRenderedPageBreak" in xml
    )


def _paragraph_html(paragraph: Paragraph) -> str:
    fragments: list[str] = []
    for run in paragraph.runs:
        text = escape(run.text).replace("\n", "<br>")
        if not text and "<w:tab" in run._r.xml:
            text = "&emsp;"
        if not text:
            continue
        styles: list[str] = []
        if run.bold:
            styles.append("font-weight:700")
        if run.italic:
            styles.append("font-style:italic")
        if run.underline:
            styles.append("text-decoration:underline")
        if run.font.size:
            styles.append(f"font-size:{run.font.size.pt:.1f}pt")
        if run.font.name:
            styles.append(f"font-family:'{escape(run.font.name)}'")
        style = f' style="{";".join(styles)}"' if styles else ""
        fragments.append(f"<span{style}>{text}</span>")

    text = "".join(fragments) or "&nbsp;"
    alignment = {
        0: "left",
        1: "center",
        2: "right",
        3: "justify",
    }.get(paragraph.alignment, "left")
    margin_top = 0
    margin_bottom = 0
    if paragraph.paragraph_format.space_before:
        margin_top = paragraph.paragraph_format.space_before.pt
    if paragraph.paragraph_format.space_after:
        margin_bottom = paragraph.paragraph_format.space_after.pt
    return (
        f'<p style="text-align:{alignment};margin:{margin_top:.1f}pt 0 '
        f'{margin_bottom:.1f}pt 0;line-height:1.25">{text}</p>'
    )


def _cell_html(cell: _Cell) -> str:
    blocks = [_block_html(block) for block in _iter_blocks(cell)]
    return "".join(blocks) or "&nbsp;"


def _table_html(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        seen_cells: set[int] = set()
        for cell in row.cells:
            cell_key = id(cell._tc)
            if cell_key in seen_cells:
                continue
            seen_cells.add(cell_key)
            grid_span = max(1, int(getattr(cell, "grid_span", 1) or 1))
            colspan = f' colspan="{grid_span}"' if grid_span > 1 else ""
            cells.append(f'<td{colspan} style="border:1px solid #333;">{_cell_html(cell)}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<table border="1" cellspacing="0" cellpadding="3" '
        'style="border:1px solid #333;border-collapse:collapse;">'
        f"{''.join(rows)}</table>"
    )


def _block_html(block: Paragraph | Table) -> str:
    if isinstance(block, Paragraph):
        html = _paragraph_html(block)
        if _paragraph_has_page_break(block):
            html = html.replace(
                'style="',
                'style="page-break-after:always;',
                1,
            )
        return html
    return _table_html(block)


def docx_to_html(source_path: str | Path) -> str:
    document = Document(source_path)
    body = "".join(_block_html(block) for block in _iter_blocks(document))
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          @page {{ size: A4 portrait; margin: 12mm; }}
          html, body {{
            font-family: "Microsoft YaHei", "SimSun", sans-serif;
            font-size: 10.5pt;
            color: #202124;
            background: white;
          }}
          body {{ margin: 0; }}
          p {{ orphans: 2; widows: 2; }}
          table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            margin: 0 0 5pt 0;
            page-break-inside: auto;
          }}
          tr {{ page-break-inside: avoid; }}
          td {{
            border: 0.6pt solid #444;
            padding: 2.5pt 4pt;
            vertical-align: middle;
            overflow-wrap: anywhere;
          }}
          td p {{ margin-top: 0; margin-bottom: 0; }}
          .page-break {{ page-break-after: always; height: 0; }}
        </style>
      </head>
      <body>{body}</body>
    </html>
    """


def _create_printer(output_path: str | Path | None = None) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    if output_path is not None:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output_path))
    return printer


def _create_text_document(html: str, printer: QPrinter) -> QTextDocument:
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setHtml(html)
    document.setPageSize(printer.pageRect(QPrinter.Unit.Point).size())
    return document


def render_html_to_pdf(html: str, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    printer = _create_printer(output_path)
    document = _create_text_document(html, printer)
    document.print_(printer)
    document.clear()
    del document
    del printer
    gc.collect()
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("离线预览 PDF 生成失败。")
    return output_path


def _hidden_subprocess_options() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _render_docx_with_com(
    source_path: str | Path,
    output_path: str | Path,
    program_id: str,
) -> bool:
    if os.name != "nt":
        return False
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    script = (
        "$ErrorActionPreference='Stop';"
        "$source=[System.IO.Path]::GetFullPath($env:DOCSWIFT_PREVIEW_SOURCE);"
        "$output=[System.IO.Path]::GetFullPath($env:DOCSWIFT_PREVIEW_OUTPUT);"
        "$office=$null;$document=$null;"
        "try {"
        "$office=New-Object -ComObject $env:DOCSWIFT_PREVIEW_PROGID;"
        "$office.Visible=$false;$office.DisplayAlerts=0;"
        "$document=$office.Documents.Open($source,$false,$true);"
        "$document.ExportAsFixedFormat($output,17);"
        "} finally {"
        "if($null -ne $document){$document.Close($false)};"
        "if($null -ne $office){$office.Quit()};"
        "}"
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    environment = os.environ.copy()
    environment["DOCSWIFT_PREVIEW_SOURCE"] = str(source_path)
    environment["DOCSWIFT_PREVIEW_OUTPUT"] = str(output_path)
    environment["DOCSWIFT_PREVIEW_PROGID"] = program_id
    try:
        with _NATIVE_RENDER_LOCK:
            completed = subprocess.run(
                command,
                capture_output=True,
                env=environment,
                text=True,
                timeout=120,
                check=False,
                **_hidden_subprocess_options(),
            )
    except (OSError, subprocess.TimeoutExpired):
        output_path.unlink(missing_ok=True)
        return False
    if (
        completed.returncode != 0
        or not output_path.exists()
        or output_path.stat().st_size == 0
    ):
        output_path.unlink(missing_ok=True)
        return False
    return True


def render_docx_with_office(
    source_path: str | Path,
    output_path: str | Path,
) -> bool:
    """Preserve the original office layout without sending files online.

    WPS is preferred because it is the application's supported office suite.
    Microsoft Word is a compatible local fallback. If neither automation
    interface exists, ``prepare_preview`` uses the structured HTML renderer.
    """

    for program_id in ("kwps.Application", "Word.Application"):
        if _render_docx_with_com(source_path, output_path, program_id):
            return True
    return False


def _cache_key(source_path: Path) -> str:
    stat = source_path.stat()
    payload = (
        f"{str(source_path.resolve()).casefold()}|{stat.st_size}|{stat.st_mtime_ns}|"
        f"{PREVIEW_RENDERER_VERSION}"
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def prepare_preview(
    source_path: str | Path,
    cache_directory: str | Path | None = None,
) -> PreviewResult:
    source_path = Path(source_path)
    cache = (
        Path(cache_directory)
        if cache_directory is not None
        else default_preview_cache_directory()
    )
    cache.mkdir(parents=True, exist_ok=True)
    pdf_path = cache / f"{_cache_key(source_path)}.pdf"
    if not pdf_path.exists():
        renderer = os.environ.get("DOCSWIFT_PREVIEW_RENDERER", "auto").casefold()
        rendered = (
            renderer != "html"
            and render_docx_with_office(source_path, pdf_path)
        )
        if not rendered:
            html = docx_to_html(source_path)
            render_html_to_pdf(html, pdf_path)
    with pdf_path.open("rb") as pdf_stream:
        page_count = len(PdfReader(pdf_stream).pages)
    return PreviewResult(
        pdf_path=pdf_path,
        page_count=page_count,
    )


def locate_docx_content_pages(
    source_path: str | Path,
    contents: Iterable[str],
    operation_numbers: Iterable[str] | None = None,
    work_types: Iterable[str] | None = None,
) -> list[tuple[int | None, int | None]]:
    """Locate operation text in the same offline layout used for preview."""
    content_list = list(contents)
    operation_number_list = (
        list(operation_numbers)
        if operation_numbers is not None
        else [""] * len(content_list)
    )
    work_type_list = (
        list(work_types)
        if work_types is not None
        else [""] * len(content_list)
    )
    if len(operation_number_list) != len(content_list):
        raise ValueError("工序号数量与工序内容数量不一致。")
    if len(work_type_list) != len(content_list):
        raise ValueError("工种数量与工序内容数量不一致。")
    preview = prepare_preview(source_path)
    pdf_results = _locate_content_in_pdf(
        preview.pdf_path,
        content_list,
        operation_number_list,
        work_type_list,
    )
    if all(result != (None, None) for result in pdf_results):
        return pdf_results

    # Qt's HTML document keeps text positions searchable even on computers
    # without Word. Use it only for entries PDF text extraction could not find.
    html = docx_to_html(source_path)
    printer = _create_printer()
    document = _create_text_document(html, printer)
    document.pageCount()
    page_height = document.pageSize().height()
    if page_height <= 0:
        return pdf_results

    results: list[tuple[int | None, int | None]] = []
    for result_index, content in enumerate(content_list):
        if pdf_results[result_index] != (None, None):
            results.append(pdf_results[result_index])
            continue
        line_pages: list[int] = []
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        anchor_cursor = None
        operation_no = operation_number_list[result_index].strip()
        work_type = work_type_list[result_index].strip()
        if operation_no and lines:
            for anchor in (
                f"{work_type} {operation_no} {lines[0]}".strip(),
                f"{operation_no} {lines[0]}",
                f"{work_type} {operation_no}".strip(),
            ):
                found = document.find(anchor)
                if not found.isNull():
                    anchor_cursor = found
                    block_rect = document.documentLayout().blockBoundingRect(
                        found.block()
                    )
                    line_pages.append(
                        int((block_rect.top() + 1.0) // page_height) + 1
                    )
                    break
        for line_index, line in enumerate(lines):
            if anchor_cursor is not None and line_index == 0:
                continue
            candidates = (line, line[:36], line[:24], line[:14], line[:8])
            cursor = None
            for candidate in candidates:
                if not candidate:
                    continue
                start_position = (
                    anchor_cursor.position()
                    if anchor_cursor is not None
                    else 0
                )
                found = document.find(candidate, start_position)
                if not found.isNull():
                    cursor = found
                    break
            if cursor is None:
                continue
            block_rect = document.documentLayout().blockBoundingRect(cursor.block())
            # Qt can place a block a few thousandths of a point before the
            # nominal page boundary, so include a one-point tolerance.
            line_pages.append(int((block_rect.top() + 1.0) // page_height) + 1)
        results.append(
            (min(line_pages), max(line_pages)) if line_pages else (None, None)
        )
    return results


def _normalize_search_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _locate_content_in_pdf(
    pdf_path: str | Path,
    contents: Iterable[str],
    operation_numbers: Iterable[str] | None = None,
    work_types: Iterable[str] | None = None,
) -> list[tuple[int | None, int | None]]:
    content_list = list(contents)
    operation_number_list = (
        list(operation_numbers)
        if operation_numbers is not None
        else [""] * len(content_list)
    )
    work_type_list = (
        list(work_types)
        if work_types is not None
        else [""] * len(content_list)
    )
    try:
        with Path(pdf_path).open("rb") as pdf_stream:
            reader = PdfReader(pdf_stream)
            page_texts = [
                _normalize_search_text(page.extract_text() or "")
                for page in reader.pages
            ]
    except Exception:
        return [(None, None) for _ in content_list]

    results: list[tuple[int | None, int | None]] = []
    for index, content in enumerate(content_list):
        located_pages: list[int] = []
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        anchor_page: int | None = None
        operation_no = operation_number_list[index].strip()
        work_type = work_type_list[index].strip()
        if operation_no and lines:
            anchor_candidates = (
                _normalize_search_text(
                    f"{work_type} {operation_no} {lines[0]}"
                ),
                _normalize_search_text(f"{operation_no} {lines[0]}"),
                _normalize_search_text(f"{work_type} {operation_no}"),
            )
            for page_number, page_text in enumerate(page_texts, start=1):
                if any(
                    candidate and candidate in page_text
                    for candidate in anchor_candidates
                ):
                    anchor_page = page_number
                    located_pages.append(page_number)
                    break
        for line in lines:
            normalized_line = _normalize_search_text(line)
            candidates = (
                normalized_line,
                normalized_line[:36],
                normalized_line[:24],
                normalized_line[:14],
                normalized_line[:8],
            )
            start_page = anchor_page or 1
            for page_number in range(start_page, len(page_texts) + 1):
                page_text = page_texts[page_number - 1]
                if any(candidate and candidate in page_text for candidate in candidates):
                    located_pages.append(page_number)
                    break
        results.append(
            (min(located_pages), max(located_pages))
            if located_pages
            else (None, None)
        )
    return results
