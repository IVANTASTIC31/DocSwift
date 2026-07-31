from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from core import (
    OperationRow,
    ProcessCard,
    generate_template_atomic,
    group_operations,
    parse_process_card,
)
from domain import CardRecord, CardStatus, EditableOperation, TaskRecord
from project_store import ProjectStore
from preview_service import (
    PreviewResult,
    locate_docx_content_pages,
    prepare_preview,
)


@dataclass(frozen=True)
class RecognitionPayload:
    route_no: str
    route_name: str
    operations: list[dict[str, object]]
    original_snapshot: list[dict[str, object]]
    excluded_snapshot: list[dict[str, object]]


@dataclass(frozen=True)
class RecognitionResult:
    payload: RecognitionPayload
    preview: PreviewResult | None
    preview_error: str = ""


def recognize_docx(
    source_path: str | Path,
    exclusion_terms: Sequence[str],
) -> RecognitionPayload:
    card = parse_process_card(source_path)
    grouped = group_operations(card.operations, exclusion_terms)
    operations = [
        {
            "operation_no": operation.operation_no,
            "original_range": operation.original_range,
            "work_type": operation.work_type,
            "content": operation.content,
            "source_page_start": None,
            "source_page_end": None,
        }
        for operation in grouped.operations
    ]
    return RecognitionPayload(
        route_no=card.part_no,
        route_name=card.part_name,
        operations=operations,
        original_snapshot=[asdict(operation) for operation in card.operations],
        excluded_snapshot=[asdict(operation) for operation in grouped.excluded],
    )


def recognize_docx_complete(
    source_path: str | Path,
    exclusion_terms: Sequence[str],
) -> RecognitionResult:
    """Run parsing, preview generation and source-page location off the UI thread."""
    payload = recognize_docx(source_path, exclusion_terms)
    preview: PreviewResult | None = None
    preview_error = ""
    try:
        preview = prepare_preview(source_path)
        pages = locate_docx_content_pages(
            source_path,
            [str(operation["content"]) for operation in payload.operations],
            [str(operation["operation_no"]) for operation in payload.operations],
            [str(operation["work_type"]) for operation in payload.operations],
        )
        for operation, page_range in zip(payload.operations, pages):
            operation["source_page_start"] = page_range[0]
            operation["source_page_end"] = page_range[1]
    except Exception as exc:
        # Preview/source-page failure must not discard otherwise valid recognition.
        preview_error = str(exc)
    return RecognitionResult(
        payload=payload,
        preview=preview,
        preview_error=preview_error,
    )


def process_card_from_records(
    card: CardRecord,
    operations: Sequence[EditableOperation],
) -> ProcessCard:
    return ProcessCard(
        source_path=card.source_path,
        part_no=card.route_no,
        part_name=card.route_name,
        operations=[
            OperationRow(
                work_type=operation.work_type,
                operation_no=operation.operation_no,
                content=operation.content,
            )
            for operation in operations
        ],
    )


def export_confirmed_cards(
    database_path: str | Path,
    task_id: int,
) -> tuple[Path, list[int], int]:
    """Export confirmed cards atomically and persist status only after success."""
    with ProjectStore(database_path) as store:
        task: TaskRecord = store.get_task(task_id)
        template_path = Path(task.template_path)
        output_path = Path(task.output_path)
        if not task.template_path or not template_path.exists():
            raise ValueError("请选择有效的 Excel 模板。")
        if not task.output_path:
            raise ValueError("请选择目标 Excel 文件。")

        confirmed = [
            card
            for card in store.list_cards(task.id)
            if card.status == CardStatus.CONFIRMED
        ]
        if not confirmed:
            raise ValueError("没有已确认且未导出的工艺卡。")

        cards: list[ProcessCard] = []
        replace_routes: list[str] = []
        row_count = 0
        for card in confirmed:
            operations = store.list_operations(card.id)
            if not operations:
                raise ValueError(f"{card.display_name} 没有可导出的最终工序。")
            cards.append(process_card_from_records(card, operations))
            row_count += len(operations)
            previous_export = store.export_record(card.id, output_path)
            if previous_export:
                replace_routes.append(previous_export.route_text)

        generated = generate_template_atomic(
            cards,
            template_path,
            output_path,
            start_row=2,
            replace_route_texts=replace_routes,
        )
        exported_ids = [card.id for card in confirmed]
        store.mark_exported(exported_ids, generated)
        return generated, exported_ids, row_count
