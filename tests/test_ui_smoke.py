import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton, QToolBar

from app import MainWindow, apply_light_palette
from domain import CardStatus
from services import RecognitionResult, recognize_docx
from tests.test_services import make_process_card


class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        apply_light_palette(cls.application)

    def test_light_palette_keeps_widget_text_visible(self) -> None:
        palette = self.application.palette()
        self.assertEqual(
            "#172033",
            palette.color(QPalette.ColorRole.ButtonText).name(),
        )
        self.assertEqual(
            "#172033",
            palette.color(QPalette.ColorRole.Text).name(),
        )
        self.assertEqual(
            "#ffffff",
            palette.color(QPalette.ColorRole.Base).name(),
        )

    def test_card_actions_are_only_in_side_panel_and_remove_is_dangerous(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            window = MainWindow(Path(temporary_directory) / "controls.db")
            try:
                button_texts = [
                    button.text() for button in window.findChildren(QPushButton)
                ]
                self.assertEqual(1, button_texts.count("添加工艺卡"))
                self.assertEqual(1, button_texts.count("添加文件夹"))
                remove_button = next(
                    button
                    for button in window.findChildren(QPushButton)
                    if button.text() == "移除"
                )
                self.assertEqual("dangerButton", remove_button.objectName())
                toolbar_texts = [
                    action.text()
                    for toolbar in window.findChildren(QToolBar)
                    for action in toolbar.actions()
                ]
                self.assertNotIn("添加工艺卡", toolbar_texts)
                self.assertNotIn("添加文件夹", toolbar_texts)
            finally:
                window.close()
                self.application.processEvents()

    def test_add_and_recognize_card(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            previous_local_app_data = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(directory)
            source = directory / "B.0001.docx"
            make_process_card(source)
            window = MainWindow(directory / "ui.db")
            try:
                card_id = window.store.add_cards(window.task.id, [source])[0].id
                window._refresh_cards()
                window.current_card_id = None
                window.card_tree.clearSelection()
                window._start_recognition([card_id])
                # Native WPS/Word preview startup can be slow on the first run.
                for _ in range(600):
                    self.application.processEvents()
                    QTest.qWait(50)
                    if card_id not in window.recognizing_cards:
                        break

                card = window.store.get_card(card_id)
                self.assertEqual(CardStatus.PENDING, card.status, card.error_message)
                self.assertEqual(3, len(window.store.list_operations(card_id)))
                self.assertIn(
                    card_id,
                    window.preview_by_card,
                    f"{window.status_label.text()} / {window.preview_hint_label.text()}",
                )
            finally:
                window.close()
                self.application.processEvents()
                if previous_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_local_app_data

    def test_recognition_queue_processes_only_one_card_at_a_time(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first_path = directory / "B.0001.docx"
            second_path = directory / "B.0002.docx"
            make_process_card(first_path)
            make_process_card(second_path)
            window = MainWindow(directory / "queue.db")
            active = 0
            maximum_active = 0
            guard = threading.Lock()

            def slow_recognition(path, exclusion_terms):
                nonlocal active, maximum_active
                with guard:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.15)
                    return RecognitionResult(
                        payload=recognize_docx(path, exclusion_terms),
                        preview=None,
                    )
                finally:
                    with guard:
                        active -= 1

            try:
                cards = window.store.add_cards(
                    window.task.id,
                    [first_path, second_path],
                )
                with patch("app.recognize_docx_complete", side_effect=slow_recognition):
                    window._start_recognition([card.id for card in cards])
                    statuses = {
                        window.store.get_card(card.id).status for card in cards
                    }
                    self.assertEqual(
                        {CardStatus.RECOGNIZING, CardStatus.QUEUED},
                        statuses,
                    )
                    queued_card = next(
                        window.store.get_card(card.id)
                        for card in cards
                        if window.store.get_card(card.id).status == CardStatus.QUEUED
                    )
                    self.assertEqual("待识别", queued_card.status.label)
                    for _ in range(200):
                        self.application.processEvents()
                        QTest.qWait(20)
                        if not window.recognizing_cards:
                            break

                self.assertEqual(1, maximum_active)
                self.assertTrue(
                    all(
                        window.store.get_card(card.id).status == CardStatus.PENDING
                        for card in cards
                    )
                )
            finally:
                window.close()
                self.application.processEvents()


    def test_long_operation_content_expands_row_and_scrolls(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "B.0001.docx"
            make_process_card(source)
            window = MainWindow(directory / "long.db")
            try:
                card = window.store.add_cards(window.task.id, [source])[0]
                long_content = "车削外圆并保证尺寸精度与表面粗糙度。" * 35
                window.store.replace_recognition(
                    card.id,
                    route_no="B.0001",
                    route_name="测试件",
                    operations=[
                        {
                            "operation_no": "4",
                            "original_range": "4",
                            "work_type": "车",
                            "content": long_content,
                        }
                    ],
                    original_snapshot=[],
                    excluded_snapshot=[],
                )
                window._load_card_details(card.id)
                wide_height = window.operations_table.rowHeight(0)
                self.assertGreater(wide_height, 120)
                window.operations_table.horizontalHeader().setSectionResizeMode(
                    3,
                    QHeaderView.ResizeMode.Interactive,
                )
                window.operations_table.setColumnWidth(3, 220)
                self.assertGreater(window.operations_table.rowHeight(0), wide_height)
                self.assertNotEqual(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                    window.operations_table.verticalScrollBarPolicy(),
                )
            finally:
                window.close()
                self.application.processEvents()

    def test_confirm_current_card_advances_to_next_pending_card(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            previous_local_app_data = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(directory)
            sources = [directory / f"B.{index}.docx" for index in (1, 2, 3)]
            for source in sources:
                make_process_card(source)
            window = MainWindow(directory / "confirm.db")
            try:
                cards = window.store.add_cards(window.task.id, sources)
                for index, card in enumerate(cards):
                    window.store.replace_recognition(
                        card.id,
                        route_no=f"B.{index + 1}",
                        route_name=f"测试件{index + 1}",
                        operations=[
                            {
                                "operation_no": "1",
                                "original_range": "1",
                                "work_type": "检验",
                                "content": f"检验{index + 1}",
                            }
                        ],
                        original_snapshot=[],
                        excluded_snapshot=[],
                    )
                window.current_card_id = cards[0].id
                with patch.object(window, "_ensure_preview"):
                    window._confirm_current_card()
                self.assertEqual(cards[1].id, window.current_card_id)
            finally:
                window.close()
                self.application.processEvents()
                if previous_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_local_app_data

    def test_confirm_last_pending_card_triggers_export_confirmation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            previous_local_app_data = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(directory)
            sources = [directory / f"B.{index}.docx" for index in (1, 2)]
            for source in sources:
                make_process_card(source)
            window = MainWindow(directory / "export.db")
            try:
                cards = window.store.add_cards(window.task.id, sources)
                for index, card in enumerate(cards):
                    window.store.replace_recognition(
                        card.id,
                        route_no=f"B.{index + 1}",
                        route_name=f"测试件{index + 1}",
                        operations=[
                            {
                                "operation_no": "1",
                                "original_range": "1",
                                "work_type": "检验",
                                "content": f"检验{index + 1}",
                            }
                        ],
                        original_snapshot=[],
                        excluded_snapshot=[],
                    )
                window.store.confirm_card(cards[0].id)
                window.current_card_id = cards[1].id
                with patch.object(window, "_export_confirmed") as export_mock, patch.object(
                    window, "_ensure_preview"
                ):
                    window._confirm_current_card()
                    export_mock.assert_called_once()
            finally:
                window.close()
                self.application.processEvents()
                if previous_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_local_app_data

    def test_confirm_does_not_trigger_export_when_incomplete_cards_remain(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            previous_local_app_data = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(directory)
            sources = [directory / f"B.{index}.docx" for index in (1, 2, 3)]
            for source in sources:
                make_process_card(source)
            window = MainWindow(directory / "incomplete.db")
            try:
                cards = window.store.add_cards(window.task.id, sources)
                for index in (0, 1):
                    card = cards[index]
                    window.store.replace_recognition(
                        card.id,
                        route_no=f"B.{index + 1}",
                        route_name=f"测试件{index + 1}",
                        operations=[
                            {
                                "operation_no": "1",
                                "original_range": "1",
                                "work_type": "检验",
                                "content": f"检验{index + 1}",
                            }
                        ],
                        original_snapshot=[],
                        excluded_snapshot=[],
                    )
                with patch.object(window, "_export_confirmed") as export_mock, patch.object(
                    window, "_ensure_preview"
                ):
                    window.current_card_id = cards[0].id
                    window._confirm_current_card()
                    self.assertEqual(cards[1].id, window.current_card_id)
                    window._confirm_current_card()
                    export_mock.assert_not_called()
            finally:
                window.close()
                self.application.processEvents()
                if previous_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_local_app_data


if __name__ == "__main__":
    unittest.main()
