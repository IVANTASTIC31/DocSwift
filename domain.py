from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CardStatus(str, Enum):
    UNRECOGNIZED = "unrecognized"
    QUEUED = "queued"
    RECOGNIZING = "recognizing"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPORTED = "exported"
    ERROR = "error"
    SOURCE_CHANGED = "source_changed"

    @property
    def label(self) -> str:
        return {
            CardStatus.UNRECOGNIZED: "未识别",
            CardStatus.QUEUED: "待识别",
            CardStatus.RECOGNIZING: "识别中",
            CardStatus.PENDING: "待确认",
            CardStatus.CONFIRMED: "已确认",
            CardStatus.EXPORTED: "已导出",
            CardStatus.ERROR: "识别异常",
            CardStatus.SOURCE_CHANGED: "源文件已变化",
        }[self]


@dataclass(frozen=True)
class TaskRecord:
    id: int
    name: str
    template_path: str
    output_path: str
    auto_recognize: bool
    archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CardRecord:
    id: int
    task_id: int
    source_path: Path
    display_name: str
    route_no: str
    route_name: str
    status: CardStatus
    sort_order: int
    source_size: int
    source_mtime_ns: int
    excluded_count: int
    error_message: str
    original_snapshot: str
    excluded_snapshot: str
    exported_output_path: str
    created_at: str
    updated_at: str

    @property
    def route_text(self) -> str:
        return f"{self.route_no}{self.route_name}".strip()


@dataclass(frozen=True)
class EditableOperation:
    id: int
    card_id: int
    position: int
    operation_no: str
    original_range: str
    work_type: str
    content: str
    source_page_start: int | None
    source_page_end: int | None
    original_operation_no: str
    original_work_type: str
    original_content: str

    @property
    def source_page_text(self) -> str:
        if self.source_page_start is None:
            return "待定位"
        if (
            self.source_page_end is None
            or self.source_page_end == self.source_page_start
        ):
            return str(self.source_page_start)
        return f"{self.source_page_start}～{self.source_page_end}"


@dataclass(frozen=True)
class ExclusionRule:
    id: int
    term: str
    built_in: bool
    enabled: bool


@dataclass(frozen=True)
class ExportRecord:
    id: int
    task_id: int
    card_id: int
    output_path: str
    route_text: str
    exported_at: str
