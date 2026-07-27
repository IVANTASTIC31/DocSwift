from __future__ import annotations

import argparse
from pathlib import Path
import sys
import traceback
from typing import Callable, Sequence

from PySide6.QtCore import (
    QLockFile,
    QObject,
    QPointF,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QPalette,
)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_version import __version__
from core import generate_template, output_row_count, parse_many_cards
from domain import CardStatus, EditableOperation, TaskRecord
from preview_service import (
    PreviewResult,
    locate_docx_content_pages,
    prepare_preview,
)
from project_store import ProjectStore, default_database_path
from services import RecognitionPayload, export_confirmed_cards, recognize_docx
from update_service import UpdateInfo, UpdateService


APP_TITLE = "DocSwift 工艺卡转工艺路线"

STATUS_COLORS = {
    CardStatus.UNRECOGNIZED: ("#64748B", "#F1F5F9"),
    CardStatus.RECOGNIZING: ("#1D4ED8", "#DBEAFE"),
    CardStatus.PENDING: ("#B45309", "#FEF3C7"),
    CardStatus.CONFIRMED: ("#047857", "#D1FAE5"),
    CardStatus.EXPORTED: ("#475569", "#E2E8F0"),
    CardStatus.ERROR: ("#B91C1C", "#FEE2E2"),
    CardStatus.SOURCE_CHANGED: ("#9A3412", "#FFEDD5"),
}


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
        else:
            self.signals.finished.emit(result)


class OperationEditorDialog(QDialog):
    def __init__(self, content: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑工序内容")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每一个步骤单独占一行："))
        self.editor = QPlainTextEdit(content)
        self.editor.setFont(QFont("Microsoft YaHei", 11))
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def content(self) -> str:
        return self.editor.toPlainText().strip()


class SplitOperationDialog(QDialog):
    def __init__(
        self,
        operation: EditableOperation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("拆分工序")
        self.resize(860, 600)
        layout = QVBoxLayout(self)

        lines = operation.content.splitlines()
        split_at = max(1, len(lines) // 2)
        first_content = "\n".join(lines[:split_at])
        second_content = "\n".join(lines[split_at:])

        form = QFormLayout()
        self.operation_no_edit = QLineEdit()
        self.work_type_edit = QLineEdit(operation.work_type)
        form.addRow("新工序号：", self.operation_no_edit)
        form.addRow("新工序名称：", self.work_type_edit)
        layout.addLayout(form)

        content_layout = QHBoxLayout()
        first_box = QVBoxLayout()
        first_box.addWidget(QLabel(f"保留在工序 {operation.operation_no}："))
        self.first_editor = QPlainTextEdit(first_content)
        first_box.addWidget(self.first_editor)
        second_box = QVBoxLayout()
        second_box.addWidget(QLabel("拆分到新工序："))
        self.second_editor = QPlainTextEdit(second_content)
        second_box.addWidget(self.second_editor)
        content_layout.addLayout(first_box, 1)
        content_layout.addLayout(second_box, 1)
        layout.addLayout(content_layout, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认拆分")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not all(
            (
                self.operation_no_edit.text().strip(),
                self.work_type_edit.text().strip(),
                self.first_editor.toPlainText().strip(),
                self.second_editor.toPlainText().strip(),
            )
        ):
            QMessageBox.warning(self, APP_TITLE, "工序号、名称和两部分内容都不能为空。")
            return
        self.accept()


class ExclusionRulesDialog(QDialog):
    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("排除项管理")
        self.resize(520, 440)
        layout = QVBoxLayout(self)
        description = QLabel(
            "工序名称或内容只要包含排除项，就不会进入最终工序表和 Excel。"
            "“待焊”为内置规则，不能删除。新增规则对重新识别后的结果生效。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        input_layout = QHBoxLayout()
        self.term_edit = QLineEdit()
        self.term_edit.setPlaceholderText("输入新的排除文字，例如：外协")
        add_button = QPushButton("添加")
        add_button.clicked.connect(self._add_rule)
        remove_button = QPushButton("删除所选")
        remove_button.clicked.connect(self._remove_rule)
        input_layout.addWidget(self.term_edit, 1)
        input_layout.addWidget(add_button)
        input_layout.addWidget(remove_button)
        layout.addLayout(input_layout)

        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        close_button.rejected.connect(self.reject)
        layout.addWidget(close_button)
        self._reload()

    def _reload(self) -> None:
        self.list_widget.clear()
        for rule in self.store.list_exclusion_rules():
            suffix = "（内置，不可删除）" if rule.built_in else ""
            item = QListWidgetItem(f"{rule.term}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, rule.built_in)
            self.list_widget.addItem(item)

    def _add_rule(self) -> None:
        try:
            self.store.add_exclusion_rule(self.term_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self.term_edit.clear()
        self._reload()

    def _remove_rule(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        try:
            self.store.remove_exclusion_rule(item.data(Qt.ItemDataRole.UserRole))
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self._reload()


class MainWindow(QMainWindow):
    def __init__(self, database_path: str | Path | None = None) -> None:
        super().__init__()
        self.store = ProjectStore(database_path)
        self.task = self.store.get_or_create_active_task()
        self.current_card_id: int | None = None
        self.preview_by_card: dict[int, PreviewResult] = {}
        self.recognizing_cards: set[int] = set()
        self.card_workers: dict[int, FunctionWorker] = {}
        self.export_worker: FunctionWorker | None = None
        self.update_worker: FunctionWorker | None = None
        self.update_service = UpdateService()
        self.loading_operations = False
        self.loading_task = False
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(3)

        self.setWindowTitle(APP_TITLE)
        self.resize(1560, 940)
        self.setMinimumSize(1120, 700)
        self._build_actions()
        self._build_ui()
        self._apply_style()
        self._load_task(self.task)
        self.source_timer = QTimer(self)
        self.source_timer.setInterval(5000)
        self.source_timer.timeout.connect(self._poll_source_changes)
        self.source_timer.start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.source_timer.stop()
        self.pdf_view.setDocument(None)
        self.pdf_document.close()
        self.store.close()
        super().closeEvent(event)

    def _build_actions(self) -> None:
        self.new_task_action = QAction("新建任务", self)
        self.new_task_action.triggered.connect(self._new_task)
        self.history_action = QAction("历史任务", self)
        self.history_action.triggered.connect(self._open_history)
        self.add_cards_action = QAction("添加工艺卡", self)
        self.add_cards_action.triggered.connect(self._add_cards)
        self.add_folder_action = QAction("添加文件夹", self)
        self.add_folder_action.triggered.connect(self._add_folder)
        self.recognize_action = QAction("识别所选", self)
        self.recognize_action.triggered.connect(self._recognize_selected)
        self.recognize_all_action = QAction("识别全部未识别", self)
        self.recognize_all_action.triggered.connect(self._recognize_all)
        self.export_action = QAction("导出已确认工艺卡", self)
        self.export_action.triggered.connect(self._export_confirmed)
        self.rules_action = QAction("排除项", self)
        self.rules_action.triggered.connect(self._manage_rules)
        self.clear_action = QAction("清空当前任务", self)
        self.clear_action.triggered.connect(self._clear_task)
        self.update_action = QAction("检查更新", self)
        self.update_action.setToolTip(f"当前版本：v{__version__}")
        self.update_action.triggered.connect(self._check_for_updates)

    def _build_ui(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addAction(self.new_task_action)
        toolbar.addAction(self.history_action)
        toolbar.addSeparator()
        toolbar.addAction(self.add_cards_action)
        toolbar.addAction(self.add_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.recognize_action)
        recognize_menu_button = QToolButton()
        recognize_menu_button.setText("更多识别")
        recognize_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        recognize_menu = QMenu(recognize_menu_button)
        recognize_menu.addAction(self.recognize_all_action)
        recognize_menu_button.setMenu(recognize_menu)
        toolbar.addWidget(recognize_menu_button)
        self.auto_recognize_checkbox = QCheckBox("自动识别")
        self.auto_recognize_checkbox.setToolTip("默认关闭；开启后，新增工艺卡会自动识别。")
        self.auto_recognize_checkbox.toggled.connect(self._auto_recognize_changed)
        toolbar.addWidget(self.auto_recognize_checkbox)
        toolbar.addSeparator()
        toolbar.addAction(self.rules_action)
        toolbar.addAction(self.export_action)
        toolbar.addSeparator()
        toolbar.addAction(self.clear_action)
        toolbar.addSeparator()
        toolbar.addAction(self.update_action)
        self.addToolBar(toolbar)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(10, 8, 10, 8)
        central_layout.setSpacing(8)

        task_bar = QFrame()
        task_bar.setObjectName("taskBar")
        task_layout = QHBoxLayout(task_bar)
        task_layout.setContentsMargins(10, 8, 10, 8)
        self.task_name_label = QLabel()
        self.task_name_label.setObjectName("taskName")
        task_layout.addWidget(self.task_name_label)
        task_layout.addSpacing(12)
        task_layout.addWidget(QLabel("Excel模板"))
        self.template_edit = QLineEdit()
        self.template_edit.setReadOnly(True)
        template_button = QPushButton("选择")
        template_button.clicked.connect(self._choose_template)
        task_layout.addWidget(self.template_edit, 2)
        task_layout.addWidget(template_button)
        task_layout.addWidget(QLabel("目标Excel"))
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        output_button = QPushButton("选择")
        output_button.clicked.connect(self._choose_output)
        task_layout.addWidget(self.output_edit, 2)
        task_layout.addWidget(output_button)
        central_layout.addWidget(task_bar)

        horizontal_splitter = QSplitter(Qt.Orientation.Horizontal)
        horizontal_splitter.setChildrenCollapsible(False)
        horizontal_splitter.addWidget(self._build_card_panel())
        horizontal_splitter.addWidget(self._build_right_panel())
        horizontal_splitter.setSizes([340, 1180])
        central_layout.addWidget(horizontal_splitter, 1)
        self.setCentralWidget(central)

        status_bar = QStatusBar()
        self.status_label = QLabel("就绪")
        self.summary_label = QLabel()
        status_bar.addWidget(self.status_label, 1)
        status_bar.addPermanentWidget(self.summary_label)
        self.setStatusBar(status_bar)

    def _build_card_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        header_layout = QHBoxLayout()
        title = QLabel("工艺卡")
        title.setObjectName("sectionTitle")
        self.card_count_label = QLabel()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.card_count_label)
        layout.addLayout(header_layout)

        self.card_tree = QTreeWidget()
        self.card_tree.setHeaderLabels(["状态", "工艺卡", "工序"])
        self.card_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.card_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.card_tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.card_tree.setRootIsDecorated(False)
        self.card_tree.setAlternatingRowColors(True)
        self.card_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.card_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.card_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.card_tree.itemSelectionChanged.connect(self._card_selection_changed)
        self.card_tree.model().rowsMoved.connect(self._save_card_order)
        layout.addWidget(self.card_tree, 1)

        button_layout = QHBoxLayout()
        add_button = QPushButton("添加工艺卡")
        add_button.clicked.connect(self._add_cards)
        folder_button = QPushButton("添加文件夹")
        folder_button.clicked.connect(self._add_folder)
        remove_button = QPushButton("移除")
        remove_button.clicked.connect(self._remove_selected_cards)
        button_layout.addWidget(add_button)
        button_layout.addWidget(folder_button)
        button_layout.addWidget(remove_button)
        layout.addLayout(button_layout)
        return panel

    def _build_right_panel(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_preview_panel())
        splitter.addWidget(self._build_operations_panel())
        splitter.setSizes([520, 390])
        return splitter

    def _build_preview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contentPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        toolbar_layout = QHBoxLayout()
        title = QLabel("Word离线预览")
        title.setObjectName("sectionTitle")
        self.preview_hint_label = QLabel("选择左侧工艺卡查看")
        self.preview_hint_label.setObjectName("mutedLabel")
        toolbar_layout.addWidget(title)
        toolbar_layout.addWidget(self.preview_hint_label)
        toolbar_layout.addStretch()
        previous_button = QPushButton("上一页")
        previous_button.clicked.connect(lambda: self._change_page(-1))
        next_button = QPushButton("下一页")
        next_button.clicked.connect(lambda: self._change_page(1))
        fit_button = QPushButton("适合窗口")
        fit_button.clicked.connect(self._fit_preview)
        zoom_out_button = QPushButton("缩小")
        zoom_out_button.clicked.connect(lambda: self._zoom_preview(0.85))
        zoom_in_button = QPushButton("放大")
        zoom_in_button.clicked.connect(lambda: self._zoom_preview(1.18))
        self.page_label = QLabel("0 / 0")
        toolbar_layout.addWidget(previous_button)
        toolbar_layout.addWidget(next_button)
        toolbar_layout.addWidget(self.page_label)
        toolbar_layout.addWidget(fit_button)
        toolbar_layout.addWidget(zoom_out_button)
        toolbar_layout.addWidget(zoom_in_button)
        layout.addLayout(toolbar_layout)

        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self._page_changed)
        layout.addWidget(self.pdf_view, 1)
        return panel

    def _build_operations_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contentPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        identity_layout = QHBoxLayout()
        title = QLabel("识别与校对")
        title.setObjectName("sectionTitle")
        self.card_status_label = QLabel("未选择")
        identity_layout.addWidget(title)
        identity_layout.addWidget(self.card_status_label)
        identity_layout.addSpacing(12)
        identity_layout.addWidget(QLabel("工艺路线编号"))
        self.route_no_edit = QLineEdit()
        self.route_no_edit.setMaximumWidth(210)
        self.route_no_edit.editingFinished.connect(self._save_card_identity)
        identity_layout.addWidget(self.route_no_edit)
        identity_layout.addWidget(QLabel("名称"))
        self.route_name_edit = QLineEdit()
        self.route_name_edit.setMaximumWidth(190)
        self.route_name_edit.editingFinished.connect(self._save_card_identity)
        identity_layout.addWidget(self.route_name_edit)
        identity_layout.addStretch()
        self.excluded_label = QLabel()
        self.excluded_label.setObjectName("warningLabel")
        identity_layout.addWidget(self.excluded_label)
        layout.addLayout(identity_layout)

        self.operations_table = QTableWidget(0, 5)
        self.operations_table.setHorizontalHeaderLabels(
            ["工序号", "原始范围", "工序名称", "工序内容", "来源页"]
        )
        self.operations_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.operations_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.operations_table.setWordWrap(True)
        self.operations_table.setAlternatingRowColors(True)
        self.operations_table.verticalHeader().setVisible(False)
        header = self.operations_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.operations_table.itemChanged.connect(self._operation_item_changed)
        self.operations_table.itemDoubleClicked.connect(self._operation_double_clicked)
        self.operations_table.itemSelectionChanged.connect(self._operation_selection_changed)
        layout.addWidget(self.operations_table, 1)

        action_layout = QHBoxLayout()
        self.add_operation_button = QPushButton("新增工序")
        self.add_operation_button.clicked.connect(self._add_operation)
        self.delete_operation_button = QPushButton("删除")
        self.delete_operation_button.clicked.connect(self._delete_operations)
        self.merge_operation_button = QPushButton("合并所选")
        self.merge_operation_button.clicked.connect(self._merge_operations)
        self.split_operation_button = QPushButton("拆分")
        self.split_operation_button.clicked.connect(self._split_operation)
        self.move_up_button = QPushButton("上移")
        self.move_up_button.clicked.connect(lambda: self._move_operation(-1))
        self.move_down_button = QPushButton("下移")
        self.move_down_button.clicked.connect(lambda: self._move_operation(1))
        self.restore_button = QPushButton("恢复识别结果")
        self.restore_button.clicked.connect(self._recognize_selected)
        self.confirm_button = QPushButton("确认当前工艺卡")
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.clicked.connect(self._confirm_current_card)
        self.reopen_button = QPushButton("重新编辑")
        self.reopen_button.clicked.connect(self._reopen_current_card)
        for button in (
            self.add_operation_button,
            self.delete_operation_button,
            self.merge_operation_button,
            self.split_operation_button,
            self.move_up_button,
            self.move_down_button,
            self.restore_button,
        ):
            action_layout.addWidget(button)
        action_layout.addStretch()
        action_layout.addWidget(self.reopen_button)
        action_layout.addWidget(self.confirm_button)
        layout.addLayout(action_layout)

        advanced_label = QLabel(
            "高级字段：类型=工序　报工数配比=1　是否锁定最后一道工序=空　工时/分钟=空"
        )
        advanced_label.setObjectName("mutedLabel")
        layout.addWidget(advanced_label)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #F3F6FA; }
            QWidget {
                font-family: "Microsoft YaHei"; font-size: 10pt;
                color: #172033;
            }
            QToolBar {
                background: white; border-bottom: 1px solid #D8DEE8;
                spacing: 5px; padding: 5px;
            }
            QToolButton, QPushButton {
                background: white; border: 1px solid #C9D2DF;
                border-radius: 5px; padding: 6px 10px; color: #172033;
            }
            QToolButton:hover, QPushButton:hover { background: #EEF4FF; border-color: #7AA7F8; }
            QToolButton:disabled, QPushButton:disabled {
                background: #F8FAFC; border-color: #E2E8F0; color: #94A3B8;
            }
            QPushButton#primaryButton { background: #2563EB; color: white; border-color: #2563EB; }
            QPushButton#primaryButton:hover { background: #1D4ED8; }
            QFrame#taskBar, QFrame#sidePanel, QFrame#contentPanel {
                background: white; border: 1px solid #DCE3ED; border-radius: 7px;
            }
            QLabel#taskName, QLabel#sectionTitle { font-size: 12pt; font-weight: 700; color: #172033; }
            QLabel#mutedLabel { color: #6B7280; }
            QLabel#warningLabel { color: #B45309; font-weight: 600; }
            QLineEdit, QPlainTextEdit, QTableWidget, QTreeWidget, QListWidget {
                background: white; border: 1px solid #CCD5E1; border-radius: 4px;
                color: #172033; selection-background-color: #DBEAFE;
                selection-color: #172033;
            }
            QLineEdit:read-only { background: #F8FAFC; color: #334155; }
            QTableWidget::item, QTreeWidget::item, QListWidget::item {
                color: #172033;
            }
            QHeaderView::section {
                background: #EEF2F7; color: #334155; border: none;
                border-right: 1px solid #D8DEE8; border-bottom: 1px solid #D8DEE8;
                padding: 7px; font-weight: 600;
            }
            QMenu {
                background: white; color: #172033;
                border: 1px solid #D8DEE8; padding: 4px;
            }
            QMenu::item:selected { background: #DBEAFE; color: #172033; }
            QCheckBox { color: #172033; spacing: 6px; }
            QStatusBar {
                background: white; color: #334155;
                border-top: 1px solid #D8DEE8;
            }
            QToolTip {
                background: white; color: #172033;
                border: 1px solid #94A3B8; padding: 4px;
            }
            """
        )

    def _load_task(self, task: TaskRecord) -> None:
        self.loading_task = True
        self.task = task
        self.task_name_label.setText(task.name)
        self.template_edit.setText(task.template_path)
        self.output_edit.setText(task.output_path)
        self.auto_recognize_checkbox.setChecked(task.auto_recognize)
        self.loading_task = False
        self.current_card_id = None
        self._refresh_cards()
        self._clear_card_details()
        self.status_label.setText("已恢复上次任务")

    def _refresh_cards(self, select_card_id: int | None = None) -> None:
        selected_id = select_card_id or self.current_card_id
        cards = self.store.list_cards(self.task.id)
        self.card_tree.blockSignals(True)
        self.card_tree.clear()
        selected_item: QTreeWidgetItem | None = None
        counts = {status: 0 for status in CardStatus}
        for card in cards:
            counts[card.status] += 1
            operation_count = len(self.store.list_operations(card.id))
            route = card.route_text
            second_line = f"\n{route}" if route else ""
            item = QTreeWidgetItem(
                [card.status.label, f"{card.display_name}{second_line}", str(operation_count)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, card.id)
            foreground, background = STATUS_COLORS[card.status]
            item.setForeground(0, QColor(foreground))
            item.setBackground(0, QColor(background))
            if card.error_message:
                item.setToolTip(1, card.error_message)
            self.card_tree.addTopLevelItem(item)
            if card.id == selected_id:
                selected_item = item
        self.card_tree.blockSignals(False)
        if selected_item:
            self.card_tree.setCurrentItem(selected_item)
        self.card_count_label.setText(f"{len(cards)} 张")
        self.summary_label.setText(
            f"待确认 {counts[CardStatus.PENDING]}　"
            f"已确认 {counts[CardStatus.CONFIRMED]}　"
            f"已导出 {counts[CardStatus.EXPORTED]}"
        )

    def _selected_card_ids(self) -> list[int]:
        return [
            int(item.data(0, Qt.ItemDataRole.UserRole))
            for item in self.card_tree.selectedItems()
        ]

    def _card_selection_changed(self) -> None:
        selected = self._selected_card_ids()
        if not selected:
            return
        self.current_card_id = selected[0]
        self._load_card_details(self.current_card_id)
        self._ensure_preview(self.current_card_id)

    def _load_card_details(self, card_id: int) -> None:
        card = self.store.get_card(card_id)
        self.loading_operations = True
        self.card_status_label.setText(card.status.label)
        foreground, background = STATUS_COLORS[card.status]
        self.card_status_label.setStyleSheet(
            f"color:{foreground};background:{background};padding:4px 8px;border-radius:4px;"
        )
        self.route_no_edit.setText(card.route_no)
        self.route_name_edit.setText(card.route_name)
        self.excluded_label.setText(
            f"已排除 {card.excluded_count} 条" if card.excluded_count else ""
        )
        self.operations_table.setRowCount(0)
        operations = self.store.list_operations(card_id)
        for row_index, operation in enumerate(operations):
            self.operations_table.insertRow(row_index)
            values = (
                operation.operation_no,
                operation.original_range,
                operation.work_type,
                operation.content,
                operation.source_page_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, operation.id)
                if column in (1, 4):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 3:
                    item.setToolTip("双击打开多行编辑窗口")
                self.operations_table.setItem(row_index, column, item)
            self.operations_table.setRowHeight(
                row_index, min(120, max(38, 22 * (operation.content.count("\n") + 1)))
            )
        locked = card.status in (CardStatus.EXPORTED, CardStatus.SOURCE_CHANGED)
        self.operations_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
            if locked
            else QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.route_no_edit.setReadOnly(locked)
        self.route_name_edit.setReadOnly(locked)
        for button in (
            self.add_operation_button,
            self.delete_operation_button,
            self.merge_operation_button,
            self.split_operation_button,
            self.move_up_button,
            self.move_down_button,
            self.restore_button,
        ):
            button.setEnabled(not locked and card.status != CardStatus.UNRECOGNIZED)
        self.confirm_button.setEnabled(
            card.status in (CardStatus.PENDING, CardStatus.CONFIRMED)
        )
        self.reopen_button.setText(
            "继续使用旧结果"
            if card.status == CardStatus.SOURCE_CHANGED
            else "重新编辑"
        )
        self.reopen_button.setEnabled(
            card.status in (CardStatus.EXPORTED, CardStatus.SOURCE_CHANGED)
        )
        self.loading_operations = False

    def _clear_card_details(self) -> None:
        self.loading_operations = True
        self.card_status_label.setText("未选择")
        self.route_no_edit.clear()
        self.route_name_edit.clear()
        self.excluded_label.clear()
        self.operations_table.setRowCount(0)
        self.loading_operations = False
        self.pdf_document.close()
        self.page_label.setText("0 / 0")
        self.preview_hint_label.setText("选择左侧工艺卡查看")

    def _add_cards(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加一个或多个工艺卡",
            str(Path.home() / "Desktop"),
            "Word 工艺卡 (*.docx)",
        )
        self._add_card_paths([Path(path) for path in paths])

    def _add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择工艺卡文件夹",
            str(Path.home() / "Desktop"),
        )
        if not directory:
            return
        paths = [
            path
            for path in Path(directory).rglob("*.docx")
            if path.is_file()
            and path.suffix.casefold() == ".docx"
            and not path.name.startswith("~$")
        ]
        self._add_card_paths(paths)

    def _add_card_paths(self, paths: Sequence[Path]) -> None:
        if not paths:
            return
        try:
            added = self.store.add_cards(self.task.id, paths)
        except OSError as exc:
            QMessageBox.critical(self, APP_TITLE, f"添加工艺卡失败：\n{exc}")
            return
        if not added:
            self.status_label.setText("所选工艺卡已经在当前任务中")
            return
        self._refresh_cards(select_card_id=added[0].id)
        self.status_label.setText(f"已添加 {len(added)} 张工艺卡")
        if self.task.auto_recognize:
            self._start_recognition([card.id for card in added])

    def _remove_selected_cards(self) -> None:
        card_ids = self._selected_card_ids()
        if not card_ids:
            return
        if (
            QMessageBox.question(
                self,
                APP_TITLE,
                f"确定从当前任务移除 {len(card_ids)} 张工艺卡吗？\n"
                "原始 Word 文件不会被删除。",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        for card_id in card_ids:
            self.store.remove_card(card_id)
        self.current_card_id = None
        self._refresh_cards()
        self._clear_card_details()

    def _save_card_order(self, *_args: object) -> None:
        ordered_ids = [
            int(self.card_tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole))
            for index in range(self.card_tree.topLevelItemCount())
        ]
        self.store.set_card_order(self.task.id, ordered_ids)

    def _poll_source_changes(self) -> None:
        before = {
            card.id: card.status
            for card in self.store.list_cards(self.task.id, refresh_sources=False)
        }
        after = self.store.list_cards(self.task.id, refresh_sources=True)
        if any(before.get(card.id) != card.status for card in after):
            self._refresh_cards(select_card_id=self.current_card_id)
            if self.current_card_id:
                self._load_card_details(self.current_card_id)
            self.status_label.setText("检测到源 Word 文件发生变化")

    def _recognize_selected(self) -> None:
        card_ids = self._selected_card_ids()
        if not card_ids and self.current_card_id:
            card_ids = [self.current_card_id]
        self._start_recognition(card_ids)

    def _recognize_all(self) -> None:
        cards = self.store.list_cards(self.task.id)
        self._start_recognition(
            [
                card.id
                for card in cards
                if card.status
                in (
                    CardStatus.UNRECOGNIZED,
                    CardStatus.ERROR,
                    CardStatus.SOURCE_CHANGED,
                )
            ]
        )

    def _start_recognition(self, card_ids: Sequence[int]) -> None:
        exclusions = self.store.enabled_exclusion_terms()
        queued = 0
        for card_id in card_ids:
            if card_id in self.recognizing_cards:
                continue
            try:
                card = self.store.get_card(card_id)
            except KeyError:
                continue
            self.recognizing_cards.add(card_id)
            self.store.update_card_status(card_id, CardStatus.RECOGNIZING)
            worker = FunctionWorker(
                lambda path=card.source_path, terms=exclusions: recognize_docx(path, terms)
            )
            worker.signals.finished.connect(
                lambda result, target_id=card_id: self._recognition_finished(
                    target_id, result
                ),
                Qt.ConnectionType.QueuedConnection,
            )
            worker.signals.failed.connect(
                lambda error, target_id=card_id: self._recognition_failed(
                    target_id, error
                ),
                Qt.ConnectionType.QueuedConnection,
            )
            self.card_workers[card_id] = worker
            self.thread_pool.start(worker)
            queued += 1
        if queued:
            self.status_label.setText(f"正在识别 {queued} 张工艺卡…")
            self._refresh_cards()

    def _recognition_finished(
        self,
        card_id: int,
        payload: RecognitionPayload,
    ) -> None:
        self.recognizing_cards.discard(card_id)
        self.card_workers.pop(card_id, None)
        try:
            card = self.store.get_card(card_id)
            self.store.replace_recognition(
                card_id,
                route_no=payload.route_no,
                route_name=payload.route_name,
                operations=payload.operations,
                original_snapshot=payload.original_snapshot,
                excluded_snapshot=payload.excluded_snapshot,
            )
            pages = locate_docx_content_pages(
                card.source_path,
                [str(operation["content"]) for operation in payload.operations],
                [
                    str(operation["operation_no"])
                    for operation in payload.operations
                ],
                [str(operation["work_type"]) for operation in payload.operations],
            )
            operations = self.store.list_operations(card_id)
            for operation, page_range in zip(operations, pages):
                self.store.update_operation(
                    operation.id,
                    source_page_start=page_range[0],
                    source_page_end=page_range[1],
                    update_pages=True,
                )
        except Exception as exc:
            self._recognition_failed(card_id, str(exc))
            return
        try:
            preview = prepare_preview(card.source_path)
        except Exception as exc:
            preview = None
            self.preview_hint_label.setText("预览生成失败，可继续校对和导出")
            self.status_label.setText(str(exc))
        if preview is not None:
            self.preview_by_card[card_id] = preview
        self._refresh_cards(select_card_id=card_id if self.current_card_id == card_id else None)
        if self.current_card_id == card_id:
            self._load_card_details(card_id)
            if preview is not None:
                self._load_preview(card_id, preview)
        self.status_label.setText("识别完成，等待人工确认")

    def _recognition_failed(self, card_id: int, error: str) -> None:
        self.recognizing_cards.discard(card_id)
        self.card_workers.pop(card_id, None)
        short_error = error.strip().splitlines()[-1] if error.strip() else "未知错误"
        try:
            self.store.update_card_status(
                card_id,
                CardStatus.ERROR,
                error_message=short_error,
            )
        except KeyError:
            return
        self._refresh_cards(select_card_id=card_id if self.current_card_id == card_id else None)
        if self.current_card_id == card_id:
            self._load_card_details(card_id)
        self.status_label.setText(f"识别失败：{short_error}")

    def _ensure_preview(self, card_id: int) -> None:
        cached = self.preview_by_card.get(card_id)
        if cached:
            self._load_preview(card_id, cached)
            return
        card = self.store.get_card(card_id)
        if not card.source_path.exists():
            self.preview_hint_label.setText("源文件不存在")
            return
        self.preview_hint_label.setText("正在生成本地预览…")
        try:
            preview = prepare_preview(card.source_path)
        except Exception as exc:
            self.preview_hint_label.setText("预览生成失败，可继续识别和导出")
            self.status_label.setText(str(exc))
            return
        self.preview_by_card[card_id] = preview
        operations = self.store.list_operations(card_id)
        if operations:
            pages = locate_docx_content_pages(
                card.source_path,
                [operation.content for operation in operations],
                [operation.operation_no for operation in operations],
                [operation.work_type for operation in operations],
            )
            for operation, page_range in zip(operations, pages):
                self.store.update_operation(
                    operation.id,
                    source_page_start=page_range[0],
                    source_page_end=page_range[1],
                    update_pages=True,
                )
            if self.current_card_id == card_id:
                self._load_card_details(card_id)
        self._load_preview(card_id, preview)

    def _load_preview(self, card_id: int, preview: PreviewResult) -> None:
        if self.current_card_id != card_id:
            return
        self.pdf_document.close()
        error = self.pdf_document.load(str(preview.pdf_path))
        if error != QPdfDocument.Error.None_:
            self.preview_hint_label.setText("PDF预览加载失败")
            return
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.preview_hint_label.setText("本地 Office 原版预览，不上传源文件")
        self.page_label.setText(f"1 / {preview.page_count}")

    def _page_changed(self, page: int) -> None:
        self.page_label.setText(f"{page + 1} / {self.pdf_document.pageCount()}")

    def _change_page(self, offset: int) -> None:
        if self.pdf_document.pageCount() <= 0:
            return
        current = self.pdf_view.pageNavigator().currentPage()
        page = max(0, min(self.pdf_document.pageCount() - 1, current + offset))
        self.pdf_view.pageNavigator().jump(page, QPointF(), 0)

    def _fit_preview(self) -> None:
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def _zoom_preview(self, factor: float) -> None:
        current = self.pdf_view.zoomFactor()
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(max(0.25, min(4.0, current * factor)))

    def _operation_selection_changed(self) -> None:
        selected_rows = self.operations_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        page_item = self.operations_table.item(row, 4)
        if not page_item:
            return
        operation_id = page_item.data(Qt.ItemDataRole.UserRole)
        operation = next(
            (
                operation
                for operation in self.store.list_operations(self.current_card_id or -1)
                if operation.id == operation_id
            ),
            None,
        )
        if operation and operation.source_page_start:
            self.pdf_view.pageNavigator().jump(
                operation.source_page_start - 1,
                QPointF(),
                0,
            )

    def _operation_item_changed(self, item: QTableWidgetItem) -> None:
        if self.loading_operations or item.column() not in (0, 2, 3):
            return
        operation_id = item.data(Qt.ItemDataRole.UserRole)
        kwargs: dict[str, str] = {}
        if item.column() == 0:
            kwargs["operation_no"] = item.text()
        elif item.column() == 2:
            kwargs["work_type"] = item.text()
        else:
            kwargs["content"] = item.text()
        try:
            self.store.update_operation(operation_id, **kwargs)
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)

    def _operation_double_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() != 3 or self.current_card_id is None:
            return
        card = self.store.get_card(self.current_card_id)
        if card.status in (CardStatus.EXPORTED, CardStatus.SOURCE_CHANGED):
            return
        dialog = OperationEditorDialog(item.text(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.store.update_operation(
            item.data(Qt.ItemDataRole.UserRole),
            content=dialog.content,
        )
        self._refresh_cards(select_card_id=self.current_card_id)
        self._load_card_details(self.current_card_id)

    def _selected_operation_ids(self) -> list[int]:
        rows = sorted({index.row() for index in self.operations_table.selectedIndexes()})
        return [
            int(self.operations_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in rows
            if self.operations_table.item(row, 0)
        ]

    def _add_operation(self) -> None:
        if self.current_card_id is None:
            return
        selected_rows = self.operations_table.selectionModel().selectedRows()
        position = selected_rows[0].row() + 1 if selected_rows else None
        operation = self.store.add_operation(
            self.current_card_id,
            position=position,
            operation_no="新工序",
            work_type="",
            content="",
        )
        self._refresh_cards(select_card_id=self.current_card_id)
        self._load_card_details(self.current_card_id)
        for row in range(self.operations_table.rowCount()):
            if (
                self.operations_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                == operation.id
            ):
                self.operations_table.selectRow(row)
                self.operations_table.editItem(self.operations_table.item(row, 0))
                break

    def _delete_operations(self) -> None:
        operation_ids = self._selected_operation_ids()
        if not operation_ids:
            return
        if (
            QMessageBox.question(
                self, APP_TITLE, f"确定删除所选 {len(operation_ids)} 道工序吗？"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.store.delete_operations(operation_ids)
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)

    def _merge_operations(self) -> None:
        operation_ids = self._selected_operation_ids()
        try:
            self.store.merge_operations(operation_ids)
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)

    def _split_operation(self) -> None:
        operation_ids = self._selected_operation_ids()
        if len(operation_ids) != 1:
            QMessageBox.warning(self, APP_TITLE, "请选择一道工序进行拆分。")
            return
        operation = next(
            op
            for op in self.store.list_operations(self.current_card_id or -1)
            if op.id == operation_ids[0]
        )
        dialog = SplitOperationDialog(operation, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.store.split_operation(
                operation.id,
                first_content=dialog.first_editor.toPlainText(),
                second_operation_no=dialog.operation_no_edit.text(),
                second_work_type=dialog.work_type_edit.text(),
                second_content=dialog.second_editor.toPlainText(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)

    def _move_operation(self, offset: int) -> None:
        operation_ids = self._selected_operation_ids()
        if len(operation_ids) != 1:
            return
        self.store.move_operation(operation_ids[0], offset)
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)

    def _save_card_identity(self) -> None:
        if self.loading_operations or self.current_card_id is None:
            return
        card = self.store.get_card(self.current_card_id)
        if card.status in (CardStatus.EXPORTED, CardStatus.SOURCE_CHANGED):
            return
        self.store.update_card_identity(
            self.current_card_id,
            route_no=self.route_no_edit.text(),
            route_name=self.route_name_edit.text(),
        )
        self._refresh_cards(select_card_id=self.current_card_id)
        self._load_card_details(self.current_card_id)

    def _confirm_current_card(self) -> None:
        if self.current_card_id is None:
            return
        try:
            self.store.confirm_card(self.current_card_id)
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self._refresh_cards(select_card_id=self.current_card_id)
        self._load_card_details(self.current_card_id)
        self.status_label.setText("当前工艺卡已确认，可以批量导出")

    def _reopen_current_card(self) -> None:
        if self.current_card_id is None:
            return
        card = self.store.get_card(self.current_card_id)
        if card.status == CardStatus.SOURCE_CHANGED:
            self.store.continue_with_changed_source(self.current_card_id)
        else:
            self.store.update_card_status(self.current_card_id, CardStatus.PENDING)
        self._refresh_cards(select_card_id=self.current_card_id)
        self._load_card_details(self.current_card_id)

    def _choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Excel 工艺路线模板",
            self.task.template_path or str(Path.home() / "Desktop"),
            "Excel 工作簿 (*.xlsx)",
        )
        if not path:
            return
        self.task = self.store.update_task(self.task.id, template_path=path)
        self.template_edit.setText(path)

    def _choose_output(self) -> None:
        initial = self.task.output_path or str(
            Path.home() / "Desktop" / "工艺路线导入.xlsx"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择目标 Excel",
            initial,
            "Excel 工作簿 (*.xlsx)",
        )
        if not path:
            return
        old_output = self.task.output_path
        self.task = self.store.update_task(self.task.id, output_path=path)
        self.output_edit.setText(path)
        if old_output and Path(old_output).resolve() != Path(path).resolve():
            for card in self.store.list_cards(self.task.id):
                if card.status == CardStatus.EXPORTED:
                    self.store.update_card_status(card.id, CardStatus.CONFIRMED)
            self._refresh_cards(select_card_id=self.current_card_id)

    def _auto_recognize_changed(self, enabled: bool) -> None:
        if self.loading_task:
            return
        self.task = self.store.update_task(self.task.id, auto_recognize=enabled)
        self.status_label.setText(
            "自动识别已开启" if enabled else "自动识别已关闭（默认）"
        )

    def _export_confirmed(self) -> None:
        confirmed_count = sum(
            card.status == CardStatus.CONFIRMED
            for card in self.store.list_cards(self.task.id)
        )
        if not confirmed_count:
            QMessageBox.information(self, APP_TITLE, "没有已确认且未导出的工艺卡。")
            return
        if (
            QMessageBox.question(
                self,
                APP_TITLE,
                f"将 {confirmed_count} 张已确认工艺卡统一写入目标 Excel。\n"
                "如果其中任何一张失败，原 Excel 将保持不变。是否继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.export_action.setEnabled(False)
        self.status_label.setText("正在原子导出，请稍候…")
        worker = FunctionWorker(
            lambda: export_confirmed_cards(self.store.database_path, self.task.id)
        )
        worker.signals.finished.connect(
            self._export_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.failed.connect(
            self._export_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.export_worker = worker
        self.thread_pool.start(worker)

    def _export_finished(self, result: tuple[Path, list[int], int]) -> None:
        self.export_worker = None
        self.export_action.setEnabled(True)
        output_path, card_ids, row_count = result
        self._refresh_cards(select_card_id=self.current_card_id)
        if self.current_card_id:
            self._load_card_details(self.current_card_id)
        self.status_label.setText(
            f"导出成功：{len(card_ids)} 张工艺卡，共 {row_count} 行"
        )
        QMessageBox.information(
            self,
            APP_TITLE,
            f"导出完成。\n\n工艺卡：{len(card_ids)} 张\n"
            f"最终工序：{row_count} 行\n文件：{output_path}",
        )

    def _export_failed(self, error: str) -> None:
        self.export_worker = None
        self.export_action.setEnabled(True)
        short_error = error.strip().splitlines()[-1]
        self.status_label.setText(f"导出失败：{short_error}")
        QMessageBox.critical(
            self,
            APP_TITLE,
            f"导出失败，原 Excel 未被修改。\n\n{short_error}",
        )

    def _check_for_updates(self) -> None:
        if self.update_worker is not None:
            self.status_label.setText("更新任务正在运行，请稍候")
            return
        self.update_action.setEnabled(False)
        self.update_action.setText("正在检查更新…")
        self.status_label.setText("正在连接 GitHub 检查正式版本…")
        worker = FunctionWorker(lambda: self.update_service.check(__version__))
        worker.signals.finished.connect(
            self._update_check_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.failed.connect(
            self._update_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.update_worker = worker
        self.thread_pool.start(worker)

    def _update_check_finished(self, result: object) -> None:
        self.update_worker = None
        self.update_action.setEnabled(True)
        self.update_action.setText("检查更新")
        if result is None:
            self.status_label.setText(f"当前已是最新版本 v{__version__}")
            QMessageBox.information(
                self,
                "检查更新",
                f"当前已是最新版本 v{__version__}。",
            )
            return

        info = result
        if not isinstance(info, UpdateInfo):
            self._show_update_error("更新服务器返回了未知结果。")
            return
        self.status_label.setText(f"发现新版本 v{info.version}")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("发现新版本")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(
            f"DocSwift v{info.version} 已发布\n"
            f"当前版本：v{__version__}"
        )
        size_text = (
            f"{info.asset.size / (1024 * 1024):.1f} MB"
            if info.asset.size
            else "未知"
        )
        dialog.setInformativeText(
            f"更新包：{info.asset.name}\n大小：{size_text}\n\n"
            "下载完成后会先校验 SHA-256，再打开压缩包。"
        )
        dialog.setDetailedText(info.notes)
        download_button = dialog.addButton(
            "下载更新",
            QMessageBox.ButtonRole.AcceptRole,
        )
        release_button = dialog.addButton(
            "查看发布页",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton("暂不更新", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is release_button:
            QDesktopServices.openUrl(QUrl(info.release_url))
        elif clicked is download_button:
            self._download_update(info)

    def _download_update(self, info: UpdateInfo) -> None:
        self.update_action.setEnabled(False)
        self.update_action.setText(f"正在下载 v{info.version}…")
        self.status_label.setText("正在下载并校验更新包，请保持网络连接…")
        update_root = default_database_path().parent / "updates"
        worker = FunctionWorker(
            lambda: self.update_service.download(info, update_root)
        )
        worker.signals.finished.connect(
            lambda path: self._update_download_finished(info, path),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.failed.connect(
            self._update_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.update_worker = worker
        self.thread_pool.start(worker)

    def _update_download_finished(self, info: UpdateInfo, result: object) -> None:
        self.update_worker = None
        self.update_action.setEnabled(True)
        archive_path = Path(str(result))
        self.update_action.setText(f"已下载 v{info.version}")
        self.status_label.setText(f"更新包校验完成：{archive_path.name}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(archive_path)))
        QMessageBox.information(
            self,
            "更新包已下载",
            "更新包已通过 SHA-256 校验并打开。\n\n"
            "请关闭 DocSwift，把压缩包完整解压到一个新文件夹，"
            "再运行新版。确认新版正常后，可删除旧文件夹。\n\n"
            f"文件：{archive_path}",
        )

    def _update_failed(self, error: str) -> None:
        self.update_worker = None
        self.update_action.setEnabled(True)
        self.update_action.setText("检查更新")
        last_line = error.strip().splitlines()[-1]
        message = last_line.split(": ", 1)[-1]
        self._show_update_error(message)

    def _show_update_error(self, message: str) -> None:
        self.status_label.setText(f"更新失败：{message}")
        QMessageBox.warning(self, "更新失败", message)

    def _manage_rules(self) -> None:
        ExclusionRulesDialog(self.store, self).exec()

    def _new_task(self) -> None:
        if (
            QMessageBox.question(
                self,
                APP_TITLE,
                "新建任务后，当前任务会进入历史记录，所有校对内容都会保留。是否继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        task = self.store.create_task(archive_current=True)
        self._load_task(task)

    def _open_history(self) -> None:
        tasks = self.store.list_tasks()
        dialog = QDialog(self)
        dialog.setWindowTitle("历史任务")
        dialog.resize(650, 440)
        layout = QVBoxLayout(dialog)
        task_list = QListWidget()
        for task in tasks:
            state = "已归档" if task.archived else "当前"
            item = QListWidgetItem(
                f"{task.name}　[{state}]\n"
                f"目标：{task.output_path or '尚未选择'}　更新时间：{task.updated_at}"
            )
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            task_list.addItem(item)
        layout.addWidget(task_list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Open).setText("打开任务")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not task_list.currentItem():
            return
        task_id = int(task_list.currentItem().data(Qt.ItemDataRole.UserRole))
        self._load_task(self.store.set_active_task(task_id))

    def _clear_task(self) -> None:
        if (
            QMessageBox.warning(
                self,
                APP_TITLE,
                "这会清空当前任务的工艺卡、校对结果、模板和输出路径。\n"
                "原始 Word 和已生成的 Excel 不会被删除。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.store.clear_task(self.task.id)
        self._load_task(self.store.get_task(self.task.id))


def run_cli(args: argparse.Namespace) -> None:
    cards = parse_many_cards(args.card)
    output = generate_template(
        cards,
        args.template,
        args.output,
        start_row=args.start_row,
        append=args.append and not args.replace,
    )
    count = output_row_count(cards)
    print(f"生成完成：{output}")
    print(f"写入工艺卡：{len(cards)} 张，工序：{count} 行")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--card", nargs="+", help="工艺卡 Word 文件，可传入多个")
    parser.add_argument("--template", help="Excel 模板文件")
    parser.add_argument("--output", help="输出 Excel 文件")
    parser.add_argument("--start-row", type=int, default=2, help="写入起始行，默认 2")
    parser.add_argument("--append", action="store_true", help="追加到已有输出文件")
    parser.add_argument("--replace", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def apply_light_palette(application: QApplication) -> None:
    """Keep text readable regardless of the Windows light/dark preference."""

    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F3F6FA"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#2563EB"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#DBEAFE"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94A3B8"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#94A3B8"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#94A3B8"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#94A3B8"),
    )
    application.setPalette(palette)


def main() -> None:
    args = parse_args()
    if args.card or args.template or args.output:
        if not (args.card and args.template and args.output):
            raise SystemExit(
                "命令行模式需要同时提供 --card、--template 和 --output。"
            )
        run_cli(args)
        return

    application = QApplication(sys.argv)
    application.setApplicationName(APP_TITLE)
    application.setApplicationVersion(__version__)
    apply_light_palette(application)
    lock_path = default_database_path().with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(lock_path))
    instance_lock.setStaleLockTime(30_000)
    if not instance_lock.tryLock(0):
        QMessageBox.information(
            None,
            APP_TITLE,
            "DocSwift 已经在运行，请切换到已有窗口。",
        )
        return
    window = MainWindow()
    window.show()
    exit_code = application.exec()
    instance_lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
