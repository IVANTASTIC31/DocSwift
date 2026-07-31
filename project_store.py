from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Iterator, Sequence

from domain import (
    CardRecord,
    CardStatus,
    EditableOperation,
    ExclusionRule,
    ExportRecord,
    TaskRecord,
)


BUILT_IN_EXCLUSIONS = ("待焊",)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "DocSwift" / "docswift.db"


def natural_sort_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def file_signature(path: str | Path) -> tuple[int, int]:
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


class ProjectStore:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path) if database_path else default_database_path()
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self._ensure_built_in_rules()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                template_path TEXT NOT NULL DEFAULT '',
                output_path TEXT NOT NULL DEFAULT '',
                auto_recognize INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                source_path TEXT NOT NULL,
                source_path_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                route_no TEXT NOT NULL DEFAULT '',
                route_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                source_size INTEGER NOT NULL,
                source_mtime_ns INTEGER NOT NULL,
                excluded_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                original_snapshot TEXT NOT NULL DEFAULT '[]',
                excluded_snapshot TEXT NOT NULL DEFAULT '[]',
                exported_output_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, source_path_key)
            );

            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                operation_no TEXT NOT NULL,
                original_range TEXT NOT NULL DEFAULT '',
                work_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source_page_start INTEGER,
                source_page_end INTEGER,
                original_operation_no TEXT NOT NULL,
                original_work_type TEXT NOT NULL,
                original_content TEXT NOT NULL,
                UNIQUE(card_id, position)
            );

            CREATE TABLE IF NOT EXISTS exclusion_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT NOT NULL UNIQUE COLLATE NOCASE,
                built_in INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                output_path TEXT NOT NULL,
                output_path_key TEXT NOT NULL,
                route_text TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                UNIQUE(card_id, output_path_key)
            );
            """
        )
        self.connection.commit()

    def _ensure_built_in_rules(self) -> None:
        with self.transaction() as connection:
            for term in BUILT_IN_EXCLUSIONS:
                connection.execute(
                    """
                    INSERT INTO exclusion_rules(term, built_in, enabled)
                    VALUES (?, 1, 1)
                    ON CONFLICT(term) DO UPDATE SET built_in = 1, enabled = 1
                    """,
                    (term,),
                )

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return str(Path(path).resolve()).casefold()

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            name=row["name"],
            template_path=row["template_path"],
            output_path=row["output_path"],
            auto_recognize=bool(row["auto_recognize"]),
            archived=bool(row["archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _card_from_row(row: sqlite3.Row) -> CardRecord:
        return CardRecord(
            id=row["id"],
            task_id=row["task_id"],
            source_path=Path(row["source_path"]),
            display_name=row["display_name"],
            route_no=row["route_no"],
            route_name=row["route_name"],
            status=CardStatus(row["status"]),
            sort_order=row["sort_order"],
            source_size=row["source_size"],
            source_mtime_ns=row["source_mtime_ns"],
            excluded_count=row["excluded_count"],
            error_message=row["error_message"],
            original_snapshot=row["original_snapshot"],
            excluded_snapshot=row["excluded_snapshot"],
            exported_output_path=row["exported_output_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> EditableOperation:
        return EditableOperation(
            id=row["id"],
            card_id=row["card_id"],
            position=row["position"],
            operation_no=row["operation_no"],
            original_range=row["original_range"],
            work_type=row["work_type"],
            content=row["content"],
            source_page_start=row["source_page_start"],
            source_page_end=row["source_page_end"],
            original_operation_no=row["original_operation_no"],
            original_work_type=row["original_work_type"],
            original_content=row["original_content"],
        )

    def _setting(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def create_task(self, name: str | None = None, *, archive_current: bool = False) -> TaskRecord:
        timestamp = utc_now()
        with self.transaction() as connection:
            if archive_current:
                current = self.active_task()
                if current:
                    connection.execute(
                        "UPDATE tasks SET archived = 1, updated_at = ? WHERE id = ?",
                        (timestamp, current.id),
                    )
            task_name = name or f"导入任务 {datetime.now():%Y-%m-%d %H:%M}"
            cursor = connection.execute(
                """
                INSERT INTO tasks(
                    name, template_path, output_path, auto_recognize,
                    archived, created_at, updated_at
                ) VALUES (?, '', '', 0, 0, ?, ?)
                """,
                (task_name, timestamp, timestamp),
            )
            task_id = int(cursor.lastrowid)
            self._set_setting("active_task_id", str(task_id))
        return self.get_task(task_id)

    def active_task(self) -> TaskRecord | None:
        task_id = self._setting("active_task_id")
        if task_id:
            row = self.connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (int(task_id),)
            ).fetchone()
            if row:
                return self._task_from_row(row)
        row = self.connection.execute(
            "SELECT * FROM tasks ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row:
            with self.transaction():
                self._set_setting("active_task_id", str(row["id"]))
            return self._task_from_row(row)
        return None

    def get_or_create_active_task(self) -> TaskRecord:
        return self.active_task() or self.create_task()

    def get_task(self, task_id: int) -> TaskRecord:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"任务不存在：{task_id}")
        return self._task_from_row(row)

    def list_tasks(self) -> list[TaskRecord]:
        rows = self.connection.execute(
            "SELECT * FROM tasks ORDER BY archived, updated_at DESC, id DESC"
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def set_active_task(self, task_id: int) -> TaskRecord:
        self.get_task(task_id)
        with self.transaction() as connection:
            timestamp = utc_now()
            connection.execute(
                """
                UPDATE tasks SET archived = 1, updated_at = ?
                WHERE archived = 0 AND id <> ?
                """,
                (timestamp, task_id),
            )
            connection.execute(
                "UPDATE tasks SET archived = 0, updated_at = ? WHERE id = ?",
                (timestamp, task_id),
            )
            self._set_setting("active_task_id", str(task_id))
        return self.get_task(task_id)

    def update_task(
        self,
        task_id: int,
        *,
        name: str | None = None,
        template_path: str | Path | None = None,
        output_path: str | Path | None = None,
        auto_recognize: bool | None = None,
    ) -> TaskRecord:
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name.strip() or "未命名任务"
        if template_path is not None:
            changes["template_path"] = str(template_path)
        if output_path is not None:
            changes["output_path"] = str(output_path)
        if auto_recognize is not None:
            changes["auto_recognize"] = int(auto_recognize)
        if not changes:
            return self.get_task(task_id)

        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                (*changes.values(), task_id),
            )
        return self.get_task(task_id)

    def add_cards(self, task_id: int, paths: Iterable[str | Path]) -> list[CardRecord]:
        existing_order = self.connection.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS maximum FROM cards WHERE task_id = ?",
            (task_id,),
        ).fetchone()["maximum"]
        unique_paths = {
            self._path_key(path): Path(path).resolve()
            for path in paths
            if Path(path).suffix.casefold() == ".docx"
        }
        ordered_paths = sorted(
            unique_paths.values(), key=lambda path: natural_sort_key(path.name)
        )
        timestamp = utc_now()
        added_ids: list[int] = []
        with self.transaction() as connection:
            for offset, path in enumerate(ordered_paths, start=1):
                size, mtime_ns = file_signature(path)
                cursor = connection.execute(
                    """
                    INSERT INTO cards(
                        task_id, source_path, source_path_key, display_name,
                        status, sort_order, source_size, source_mtime_ns,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, source_path_key) DO NOTHING
                    """,
                    (
                        task_id,
                        str(path),
                        self._path_key(path),
                        path.name,
                        CardStatus.UNRECOGNIZED.value,
                        existing_order + offset,
                        size,
                        mtime_ns,
                        timestamp,
                        timestamp,
                    ),
                )
                if cursor.lastrowid:
                    added_ids.append(int(cursor.lastrowid))
        return [self.get_card(card_id) for card_id in added_ids]

    def get_card(self, card_id: int) -> CardRecord:
        row = self.connection.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"工艺卡不存在：{card_id}")
        return self._card_from_row(row)

    def list_cards(self, task_id: int, *, refresh_sources: bool = True) -> list[CardRecord]:
        if refresh_sources:
            self.refresh_source_states(task_id)
        rows = self.connection.execute(
            "SELECT * FROM cards WHERE task_id = ? ORDER BY sort_order, id",
            (task_id,),
        ).fetchall()
        return [self._card_from_row(row) for row in rows]

    def refresh_source_states(self, task_id: int) -> None:
        rows = self.connection.execute(
            """
            SELECT id, source_path, source_size, source_mtime_ns, status
            FROM cards WHERE task_id = ?
            """,
            (task_id,),
        ).fetchall()
        changed_ids: list[int] = []
        for row in rows:
            try:
                signature = file_signature(row["source_path"])
            except OSError:
                signature = (-1, -1)
            if signature != (row["source_size"], row["source_mtime_ns"]):
                changed_ids.append(row["id"])
        if not changed_ids:
            return
        timestamp = utc_now()
        placeholders = ",".join("?" for _ in changed_ids)
        with self.transaction() as connection:
            connection.execute(
                f"""
                UPDATE cards
                SET status = ?, updated_at = ?
                WHERE id IN ({placeholders})
                  AND status NOT IN (?, ?)
                """,
                (
                    CardStatus.SOURCE_CHANGED.value,
                    timestamp,
                    *changed_ids,
                    CardStatus.UNRECOGNIZED.value,
                    CardStatus.ERROR.value,
                ),
            )

    def update_card_status(
        self,
        card_id: int,
        status: CardStatus,
        *,
        error_message: str = "",
    ) -> CardRecord:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE cards
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, error_message, utc_now(), card_id),
            )
        return self.get_card(card_id)

    def recover_interrupted_recognition(self) -> int:
        """Put jobs interrupted by a previous shutdown back into a retryable state."""
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE cards
                SET status = ?, error_message = '', updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    CardStatus.UNRECOGNIZED.value,
                    utc_now(),
                    CardStatus.QUEUED.value,
                    CardStatus.RECOGNIZING.value,
                ),
            )
        return max(0, cursor.rowcount)

    def update_card_identity(
        self, card_id: int, *, route_no: str | None = None, route_name: str | None = None
    ) -> CardRecord:
        changes: dict[str, object] = {}
        if route_no is not None:
            changes["route_no"] = route_no.strip()
        if route_name is not None:
            changes["route_name"] = route_name.strip()
        if not changes:
            return self.get_card(card_id)
        changes.update(
            status=CardStatus.PENDING.value,
            exported_output_path="",
            updated_at=utc_now(),
        )
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE cards SET {assignments} WHERE id = ?",
                (*changes.values(), card_id),
            )
        return self.get_card(card_id)

    def replace_recognition(
        self,
        card_id: int,
        *,
        route_no: str,
        route_name: str,
        operations: Sequence[dict[str, object]],
        original_snapshot: Sequence[dict[str, object]],
        excluded_snapshot: Sequence[dict[str, object]],
    ) -> CardRecord:
        card = self.get_card(card_id)
        size, mtime_ns = file_signature(card.source_path)
        timestamp = utc_now()
        with self.transaction() as connection:
            connection.execute("DELETE FROM operations WHERE card_id = ?", (card_id,))
            for position, operation in enumerate(operations):
                connection.execute(
                    """
                    INSERT INTO operations(
                        card_id, position, operation_no, original_range,
                        work_type, content, source_page_start, source_page_end,
                        original_operation_no, original_work_type, original_content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        position,
                        str(operation.get("operation_no", "")),
                        str(operation.get("original_range", "")),
                        str(operation.get("work_type", "")),
                        str(operation.get("content", "")),
                        operation.get("source_page_start"),
                        operation.get("source_page_end"),
                        str(operation.get("operation_no", "")),
                        str(operation.get("work_type", "")),
                        str(operation.get("content", "")),
                    ),
                )
            connection.execute(
                """
                UPDATE cards SET
                    route_no = ?, route_name = ?, status = ?,
                    source_size = ?, source_mtime_ns = ?,
                    excluded_count = ?, error_message = '',
                    original_snapshot = ?, excluded_snapshot = ?,
                    exported_output_path = '', updated_at = ?
                WHERE id = ?
                """,
                (
                    route_no.strip(),
                    route_name.strip(),
                    CardStatus.PENDING.value,
                    size,
                    mtime_ns,
                    len(excluded_snapshot),
                    json.dumps(original_snapshot, ensure_ascii=False),
                    json.dumps(excluded_snapshot, ensure_ascii=False),
                    timestamp,
                    card_id,
                ),
            )
        return self.get_card(card_id)

    def list_operations(self, card_id: int) -> list[EditableOperation]:
        rows = self.connection.execute(
            "SELECT * FROM operations WHERE card_id = ? ORDER BY position, id",
            (card_id,),
        ).fetchall()
        return [self._operation_from_row(row) for row in rows]

    def update_operation(
        self,
        operation_id: int,
        *,
        operation_no: str | None = None,
        work_type: str | None = None,
        content: str | None = None,
        source_page_start: int | None = None,
        source_page_end: int | None = None,
        update_pages: bool = False,
    ) -> EditableOperation:
        row = self.connection.execute(
            "SELECT card_id FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"工序不存在：{operation_id}")
        changes: dict[str, object] = {}
        if operation_no is not None:
            changes["operation_no"] = operation_no.strip()
        if work_type is not None:
            changes["work_type"] = work_type.strip()
        if content is not None:
            changes["content"] = content.strip()
        if update_pages:
            changes["source_page_start"] = source_page_start
            changes["source_page_end"] = source_page_end
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            with self.transaction() as connection:
                connection.execute(
                    f"UPDATE operations SET {assignments} WHERE id = ?",
                    (*changes.values(), operation_id),
                )
                connection.execute(
                    """
                    UPDATE cards
                    SET status = ?, exported_output_path = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (CardStatus.PENDING.value, utc_now(), row["card_id"]),
                )
        result = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return self._operation_from_row(result)

    def add_operation(
        self,
        card_id: int,
        *,
        position: int | None = None,
        operation_no: str = "",
        work_type: str = "",
        content: str = "",
    ) -> EditableOperation:
        count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM operations WHERE card_id = ?",
            (card_id,),
        ).fetchone()["count"]
        target_position = count if position is None else max(0, min(position, count))
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE operations SET position = position + 100000
                WHERE card_id = ? AND position >= ?
                """,
                (card_id, target_position),
            )
            connection.execute(
                """
                UPDATE operations SET position = position - 99999
                WHERE card_id = ? AND position >= ?
                """,
                (card_id, target_position + 100000),
            )
            cursor = connection.execute(
                """
                INSERT INTO operations(
                    card_id, position, operation_no, original_range,
                    work_type, content, original_operation_no,
                    original_work_type, original_content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    target_position,
                    operation_no,
                    operation_no,
                    work_type,
                    content,
                    operation_no,
                    work_type,
                    content,
                ),
            )
            connection.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (CardStatus.PENDING.value, utc_now(), card_id),
            )
            operation_id = int(cursor.lastrowid)
        row = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return self._operation_from_row(row)

    def delete_operations(self, operation_ids: Sequence[int]) -> None:
        if not operation_ids:
            return
        placeholders = ",".join("?" for _ in operation_ids)
        row = self.connection.execute(
            f"SELECT card_id FROM operations WHERE id IN ({placeholders}) LIMIT 1",
            tuple(operation_ids),
        ).fetchone()
        if not row:
            return
        card_id = row["card_id"]
        with self.transaction() as connection:
            connection.execute(
                f"DELETE FROM operations WHERE id IN ({placeholders}) AND card_id = ?",
                (*operation_ids, card_id),
            )
            self._renumber_operations(connection, card_id)
            connection.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (CardStatus.PENDING.value, utc_now(), card_id),
            )

    @staticmethod
    def _renumber_operations(connection: sqlite3.Connection, card_id: int) -> None:
        rows = connection.execute(
            "SELECT id FROM operations WHERE card_id = ? ORDER BY position, id",
            (card_id,),
        ).fetchall()
        for position, row in enumerate(rows):
            connection.execute(
                "UPDATE operations SET position = ? WHERE id = ?",
                (-(position + 1), row["id"]),
            )
        connection.execute(
            "UPDATE operations SET position = -position - 1 WHERE card_id = ?",
            (card_id,),
        )

    def merge_operations(self, operation_ids: Sequence[int]) -> EditableOperation:
        if len(operation_ids) < 2:
            raise ValueError("请至少选择两道连续工序。")
        placeholders = ",".join("?" for _ in operation_ids)
        rows = self.connection.execute(
            f"""
            SELECT * FROM operations
            WHERE id IN ({placeholders})
            ORDER BY position, id
            """,
            tuple(operation_ids),
        ).fetchall()
        if len(rows) != len(set(operation_ids)):
            raise ValueError("选中的工序不存在。")
        if len({row["card_id"] for row in rows}) != 1:
            raise ValueError("只能合并同一张工艺卡的工序。")
        positions = [row["position"] for row in rows]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("只能合并连续工序。")

        card_id = rows[0]["card_id"]
        first_id = rows[0]["id"]
        range_start = rows[0]["original_range"] or rows[0]["operation_no"]
        range_end = rows[-1]["original_range"] or rows[-1]["operation_no"]
        if "～" in range_start:
            range_start = range_start.split("～", 1)[0]
        if "～" in range_end:
            range_end = range_end.rsplit("～", 1)[-1]
        original_range = (
            range_start if range_start == range_end else f"{range_start}～{range_end}"
        )
        content = "\n".join(row["content"] for row in rows if row["content"])
        pages = [
            page
            for row in rows
            for page in (row["source_page_start"], row["source_page_end"])
            if page is not None
        ]
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE operations
                SET original_range = ?, content = ?,
                    source_page_start = ?, source_page_end = ?
                WHERE id = ?
                """,
                (
                    original_range,
                    content,
                    min(pages) if pages else None,
                    max(pages) if pages else None,
                    first_id,
                ),
            )
            other_ids = [row["id"] for row in rows[1:]]
            other_placeholders = ",".join("?" for _ in other_ids)
            connection.execute(
                f"DELETE FROM operations WHERE id IN ({other_placeholders})",
                tuple(other_ids),
            )
            self._renumber_operations(connection, card_id)
            connection.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (CardStatus.PENDING.value, utc_now(), card_id),
            )
        result = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (first_id,)
        ).fetchone()
        return self._operation_from_row(result)

    def split_operation(
        self,
        operation_id: int,
        *,
        first_content: str,
        second_operation_no: str,
        second_work_type: str,
        second_content: str,
    ) -> tuple[EditableOperation, EditableOperation]:
        row = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"工序不存在：{operation_id}")
        first_content = first_content.strip()
        second_operation_no = second_operation_no.strip()
        second_work_type = second_work_type.strip()
        second_content = second_content.strip()
        if not all((first_content, second_operation_no, second_work_type, second_content)):
            raise ValueError("拆分后的工序号、名称和两部分内容都不能为空。")

        card_id = row["card_id"]
        new_position = row["position"] + 1
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE operations SET position = position + 100000
                WHERE card_id = ? AND position >= ?
                """,
                (card_id, new_position),
            )
            connection.execute(
                """
                UPDATE operations SET position = position - 99999
                WHERE card_id = ? AND position >= ?
                """,
                (card_id, new_position + 100000),
            )
            connection.execute(
                "UPDATE operations SET content = ? WHERE id = ?",
                (first_content, operation_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO operations(
                    card_id, position, operation_no, original_range,
                    work_type, content, source_page_start, source_page_end,
                    original_operation_no, original_work_type, original_content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    new_position,
                    second_operation_no,
                    second_operation_no,
                    second_work_type,
                    second_content,
                    row["source_page_start"],
                    row["source_page_end"],
                    second_operation_no,
                    second_work_type,
                    second_content,
                ),
            )
            connection.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (CardStatus.PENDING.value, utc_now(), card_id),
            )
            new_id = int(cursor.lastrowid)
        first = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        second = self.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (new_id,)
        ).fetchone()
        return self._operation_from_row(first), self._operation_from_row(second)

    def move_operation(self, operation_id: int, offset: int) -> None:
        if offset not in (-1, 1):
            raise ValueError("移动方向只能是 -1 或 1。")
        row = self.connection.execute(
            "SELECT card_id, position FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if not row:
            return
        target_position = row["position"] + offset
        target = self.connection.execute(
            """
            SELECT id FROM operations
            WHERE card_id = ? AND position = ?
            """,
            (row["card_id"], target_position),
        ).fetchone()
        if not target:
            return
        with self.transaction() as connection:
            connection.execute(
                "UPDATE operations SET position = -1 WHERE id = ?", (operation_id,)
            )
            connection.execute(
                "UPDATE operations SET position = ? WHERE id = ?",
                (row["position"], target["id"]),
            )
            connection.execute(
                "UPDATE operations SET position = ? WHERE id = ?",
                (target_position, operation_id),
            )
            connection.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (CardStatus.PENDING.value, utc_now(), row["card_id"]),
            )

    def set_card_order(self, task_id: int, ordered_card_ids: Sequence[int]) -> None:
        with self.transaction() as connection:
            for position, card_id in enumerate(ordered_card_ids):
                connection.execute(
                    """
                    UPDATE cards SET sort_order = ?, updated_at = ?
                    WHERE id = ? AND task_id = ?
                    """,
                    (position, utc_now(), card_id, task_id),
                )

    def remove_card(self, card_id: int) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    def confirm_card(self, card_id: int) -> CardRecord:
        card = self.get_card(card_id)
        operations = self.list_operations(card_id)
        if card.status == CardStatus.SOURCE_CHANGED:
            raise ValueError("源文件已经变化，请先重新识别或确认继续使用旧结果。")
        if not card.route_no or not card.route_name:
            raise ValueError("工艺路线编号和名称不能为空。")
        if not operations:
            raise ValueError("没有可确认的最终工序。")
        seen_numbers: set[str] = set()
        for operation in operations:
            if not operation.operation_no or not operation.work_type or not operation.content:
                raise ValueError("工序号、工序名称和工序内容不能为空。")
            if operation.operation_no in seen_numbers:
                raise ValueError(f"工序号重复：{operation.operation_no}")
            seen_numbers.add(operation.operation_no)
        return self.update_card_status(card_id, CardStatus.CONFIRMED)

    def continue_with_changed_source(self, card_id: int) -> CardRecord:
        card = self.get_card(card_id)
        if card.status != CardStatus.SOURCE_CHANGED:
            return card
        size, mtime_ns = file_signature(card.source_path)
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE cards
                SET status = ?, source_size = ?, source_mtime_ns = ?, updated_at = ?
                WHERE id = ?
                """,
                (CardStatus.PENDING.value, size, mtime_ns, utc_now(), card_id),
            )
        return self.get_card(card_id)

    def mark_exported(
        self, card_ids: Sequence[int], output_path: str | Path
    ) -> None:
        output = str(Path(output_path).resolve())
        output_key = output.casefold()
        timestamp = utc_now()
        with self.transaction() as connection:
            for card_id in card_ids:
                card = self.get_card(card_id)
                connection.execute(
                    """
                    INSERT INTO exports(
                        task_id, card_id, output_path, output_path_key,
                        route_text, exported_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(card_id, output_path_key) DO UPDATE SET
                        route_text = excluded.route_text,
                        exported_at = excluded.exported_at
                    """,
                    (
                        card.task_id,
                        card_id,
                        output,
                        output_key,
                        card.route_text,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    UPDATE cards
                    SET status = ?, exported_output_path = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (CardStatus.EXPORTED.value, output, timestamp, card_id),
                )

    def export_record(
        self, card_id: int, output_path: str | Path
    ) -> ExportRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM exports
            WHERE card_id = ? AND output_path_key = ?
            """,
            (card_id, self._path_key(output_path)),
        ).fetchone()
        if not row:
            return None
        return ExportRecord(
            id=row["id"],
            task_id=row["task_id"],
            card_id=row["card_id"],
            output_path=row["output_path"],
            route_text=row["route_text"],
            exported_at=row["exported_at"],
        )

    def list_exclusion_rules(self) -> list[ExclusionRule]:
        rows = self.connection.execute(
            "SELECT * FROM exclusion_rules ORDER BY built_in DESC, term COLLATE NOCASE"
        ).fetchall()
        return [
            ExclusionRule(
                id=row["id"],
                term=row["term"],
                built_in=bool(row["built_in"]),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def enabled_exclusion_terms(self) -> tuple[str, ...]:
        return tuple(rule.term for rule in self.list_exclusion_rules() if rule.enabled)

    def add_exclusion_rule(self, term: str) -> ExclusionRule:
        cleaned = term.strip()
        if not cleaned:
            raise ValueError("排除项不能为空。")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO exclusion_rules(term, built_in, enabled)
                VALUES (?, 0, 1)
                ON CONFLICT(term) DO UPDATE SET enabled = 1
                """,
                (cleaned,),
            )
        return next(rule for rule in self.list_exclusion_rules() if rule.term == cleaned)

    def remove_exclusion_rule(self, rule_id: int) -> None:
        row = self.connection.execute(
            "SELECT built_in FROM exclusion_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if row and row["built_in"]:
            raise ValueError("内置排除项不能删除。")
        with self.transaction() as connection:
            connection.execute("DELETE FROM exclusion_rules WHERE id = ?", (rule_id,))

    def clear_task(self, task_id: int) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM cards WHERE task_id = ?", (task_id,))
            connection.execute(
                """
                UPDATE tasks SET template_path = '', output_path = '',
                    auto_recognize = 0, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), task_id),
            )
