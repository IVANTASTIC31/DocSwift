from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Sequence

from docx import Document
from openpyxl import load_workbook
from openpyxl.styles import Border, Side


HEADER_ALIASES = {
    "route_no": ("工艺路线编号",),
    "route_name": ("工艺路线名称",),
    "work_type": ("工序/工艺路线列表",),
    "content": ("工序内容",),
    "operation_no": ("工艺", "工序", "工序号"),
    "type": ("类型",),
    "ratio": ("报工数配比",),
    "locked": ("是否锁定为最后一道工序",),
    "work_minutes": ("工时/分钟",),
}

THIN_BLACK_BORDER = Border(
    left=Side(style="thin", color="000000"),
    right=Side(style="thin", color="000000"),
    top=Side(style="thin", color="000000"),
    bottom=Side(style="thin", color="000000"),
)


@dataclass(frozen=True)
class OperationRow:
    work_type: str
    operation_no: str
    content: str


@dataclass(frozen=True)
class ProcessCard:
    source_path: Path
    part_no: str
    part_name: str
    operations: list[OperationRow]

    @property
    def route_text(self) -> str:
        return f"{self.part_no}{self.part_name}".strip()


def _group_operations(operations: Sequence[OperationRow]) -> list[OperationRow]:
    """Collapse continuation rows into the preceding named work type.

    Process cards commonly put the work type only on the first row of a
    multi-step operation.  Any following blank work-type row is treated as
    continuation detail.  Operations containing "待焊" are always
    excluded because they must not be imported into the work-order system.
    """
    operations = [
        operation
        for operation in operations
        if "待焊" not in f"{operation.work_type}{operation.content}"
    ]
    grouped: list[OperationRow] = []
    index = 0
    while index < len(operations):
        operation = operations[index]
        if not operation.work_type:
            grouped.append(operation)
            index += 1
            continue

        next_index = index + 1
        continuations: list[OperationRow] = []
        while next_index < len(operations) and not operations[next_index].work_type:
            continuations.append(operations[next_index])
            next_index += 1

        if continuations:
            grouped.append(
                OperationRow(
                    work_type=operation.work_type,
                    operation_no=operation.operation_no,
                    content="\n".join(
                        item.content for item in (operation, *continuations) if item.content
                    ),
                )
            )
            index = next_index
        else:
            grouped.append(operation)
            index += 1

    return grouped


def output_row_count(cards: Sequence[ProcessCard]) -> int:
    return sum(len(_group_operations(card.operations)) for card in cards)


def _content_row_height(content: str, base_height: float | None) -> float | None:
    line_count = content.count("\n") + 1
    if line_count <= 1:
        return base_height
    # Short groups tend to wrap within the wide content column, while long
    # groups are more compact.  These values reproduce the supplied reference
    # workbook (6 steps -> 177 pt; 16 steps -> 242 pt).
    estimated_height = line_count * 28.5 + 6 if line_count <= 8 else line_count * 15 + 2
    return max(base_height or 0, estimated_height)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return text.strip()


def _key_text(value: object) -> str:
    return re.sub(r"[\s|:：]+", "", _clean_text(value))


def _dedupe_repeated_cells(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


def _cell_texts(row) -> list[str]:
    return [_clean_text(cell.text) for cell in row.cells]


def _build_column_map(worksheet, header_row: int = 1) -> dict[str, int]:
    alias_lookup: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_lookup[_key_text(alias)] = field

    column_map: dict[str, int] = {}
    for col in range(1, worksheet.max_column + 1):
        key = _key_text(worksheet.cell(header_row, col).value)
        field = alias_lookup.get(key)
        if field and field not in column_map:
            column_map[field] = col

    fallback = {
        "route_no": 1,
        "route_name": 2,
        "work_type": 3,
        "operation_no": 4,
        "content": 5,
        "type": 6,
        "ratio": 7,
        "locked": 8,
        "work_minutes": 9,
    }
    for field, col in fallback.items():
        column_map.setdefault(field, col)

    return column_map


def _find_next_output_row(worksheet, start_row: int, column_map: dict[str, int]) -> int:
    content_columns = sorted(
        {
            column_map[field]
            for field in ("route_no", "route_name", "work_type", "content", "operation_no")
            if field in column_map
        }
    )
    if not content_columns:
        content_columns = list(range(1, worksheet.max_column + 1))

    for row_index in range(worksheet.max_row, start_row - 1, -1):
        if any(_clean_text(worksheet.cell(row_index, col).value) for col in content_columns):
            return row_index + 1
    return start_row


def _find_value_below(table, labels: Iterable[str]) -> str:
    wanted = set(labels)
    for row_index, row in enumerate(table.rows[:-1]):
        keys = [_key_text(cell.text) for cell in row.cells]
        for col_index, key in enumerate(keys):
            if key in wanted:
                for next_index in range(row_index + 1, min(row_index + 4, len(table.rows))):
                    value = _clean_text(table.cell(next_index, col_index).text)
                    if value and _key_text(value) not in wanted:
                        return value
    return ""


def _find_header(table) -> tuple[int, int, int, int]:
    best: tuple[int, int, int, int] | None = None
    for row_index, row in enumerate(table.rows):
        keys = [_key_text(cell.text) for cell in row.cells]
        try:
            work_col = keys.index("工种")
            no_col = keys.index("工序")
            content_col = keys.index("工序内容")
        except ValueError:
            continue
        best = (row_index, work_col, no_col, content_col)

    if best is None:
        raise ValueError("未找到包含“工种 / 工序 / 工序内容”的表头。")

    header_row, work_col, no_col, content_col = best
    return header_row, work_col, no_col, content_col


def _looks_like_operation_no(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[.\-]\d+)?", value.strip()))


def parse_process_card(path: str | Path) -> ProcessCard:
    source_path = Path(path)
    document = Document(source_path)

    part_no = ""
    part_name = ""
    operations: list[OperationRow] = []

    for table in document.tables:
        if not part_name:
            part_name = _find_value_below(table, {"零件名称"})
        if not part_no:
            part_no = _find_value_below(table, {"零件图号"})

        try:
            header_row, work_col, no_col, content_col = _find_header(table)
        except ValueError:
            continue

        for row in table.rows[header_row + 1 :]:
            values = _cell_texts(row)
            if max(work_col, no_col, content_col) >= len(values):
                continue

            work_type = values[work_col]
            operation_no = values[no_col]
            content = values[content_col]

            if not _looks_like_operation_no(operation_no):
                continue
            if not content:
                continue

            operations.append(
                OperationRow(
                    work_type=work_type,
                    operation_no=operation_no,
                    content=content,
                )
            )

    if not part_no:
        raise ValueError("未能从工艺卡中识别“零件图号”。")
    if not part_name:
        raise ValueError("未能从工艺卡中识别“零件名称”。")
    if not operations:
        raise ValueError("未能从工艺卡中识别任何工序明细。")

    return ProcessCard(
        source_path=source_path,
        part_no=part_no,
        part_name=part_name,
        operations=operations,
    )


def parse_many_cards(paths: Iterable[str | Path]) -> list[ProcessCard]:
    cards = [parse_process_card(path) for path in paths]
    if not cards:
        raise ValueError("请至少选择一个工艺卡 Word 文件。")
    return cards


def _copy_row_style(ws, template_row: int, target_row: int, max_col: int) -> None:
    if template_row <= 0:
        return

    ws.row_dimensions[target_row].height = ws.row_dimensions[template_row].height
    for col in range(1, max_col + 1):
        source = ws.cell(template_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.font:
            target.font = copy(source.font)
        if source.fill:
            target.fill = copy(source.fill)
        if source.border:
            target.border = copy(source.border)
        if source.protection:
            target.protection = copy(source.protection)


def generate_template(
    cards: Sequence[ProcessCard],
    template_path: str | Path,
    output_path: str | Path,
    start_row: int = 6,
    append: bool = False,
) -> Path:
    if start_row < 2:
        raise ValueError("起始行不能小于 2。")
    if not cards:
        raise ValueError("没有可写入的工艺卡数据。")

    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    append_to_existing = append and output_path.exists()
    workbook = load_workbook(output_path if append_to_existing else template_path)
    worksheet = workbook.active
    column_map = _build_column_map(worksheet)
    max_col = max(worksheet.max_column, max(column_map.values(), default=8), 8)
    output_max_col = max(column_map.values(), default=9)
    operation_no_col = column_map.get("operation_no")
    if operation_no_col:
        worksheet.cell(1, operation_no_col).value = "工序号"
    for col in range(1, output_max_col + 1):
        header_cell = worksheet.cell(1, col)
        alignment = copy(header_cell.alignment)
        alignment.horizontal = "center"
        alignment.vertical = "center"
        alignment.wrap_text = True
        header_cell.alignment = alignment

    row_index = _find_next_output_row(worksheet, start_row, column_map) if append_to_existing else start_row
    style_source_row = (
        max(start_row, row_index - 1)
        if append_to_existing and row_index > start_row
        else start_row if worksheet.max_row >= start_row else max(1, worksheet.max_row)
    )
    template_height = worksheet.row_dimensions[style_source_row].height
    template_styles = []
    for col in range(1, max_col + 1):
        cell = worksheet.cell(style_source_row, col)
        template_styles.append(
            {
                "style": copy(cell._style) if cell.has_style else None,
                "number_format": cell.number_format,
                "alignment": copy(cell.alignment),
                "font": copy(cell.font),
                "fill": copy(cell.fill),
                "border": copy(cell.border),
                "protection": copy(cell.protection),
            }
        )

    if not append_to_existing and worksheet.max_row >= start_row:
        worksheet.delete_rows(start_row, worksheet.max_row - start_row + 1)

    for card in cards:
        for operation in _group_operations(card.operations):
            for col, style in enumerate(template_styles, start=1):
                target = worksheet.cell(row_index, col)
                if style["style"] is not None:
                    target._style = copy(style["style"])
                target.number_format = style["number_format"]
                target.alignment = copy(style["alignment"])
                target.font = copy(style["font"])
                target.fill = copy(style["fill"])
                target.border = copy(style["border"])
                target.protection = copy(style["protection"])
            worksheet.row_dimensions[row_index].height = _content_row_height(
                operation.content, template_height
            )

            values = {
                "route_no": card.route_text,
                "route_name": card.route_text,
                "work_type": operation.work_type,
                "content": operation.content,
                "operation_no": operation.operation_no,
                "type": "工序",
                "ratio": 1,
                "locked": "",
                "work_minutes": "",
            }
            for field, value in values.items():
                col = column_map.get(field)
                if col:
                    worksheet.cell(row_index, col).value = value
            for col in range(1, output_max_col + 1):
                target_cell = worksheet.cell(row_index, col)
                target_cell.border = copy(THIN_BLACK_BORDER)
                alignment = copy(target_cell.alignment)
                alignment.horizontal = "center"
                alignment.vertical = "center"
                alignment.wrap_text = True
                target_cell.alignment = alignment
            row_index += 1

    workbook.save(output_path)
    return output_path


def preview_rows(cards: Sequence[ProcessCard]) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for card in cards:
        for operation in _group_operations(card.operations):
            rows.append(
                (
                    card.source_path.name,
                    card.route_text,
                    operation.operation_no,
                    operation.work_type,
                    operation.content,
                )
            )
    return rows
