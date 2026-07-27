import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from app import MainWindow, apply_light_palette
from domain import CardStatus
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
                for _ in range(200):
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


if __name__ == "__main__":
    unittest.main()
