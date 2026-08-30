"""Диалог библиотеки шаблонов: загрузка, версии, архив, генерация (EPIC-011 Step 3)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.permissions import Permission, has_permission
from services.authorization import AuthorizationError
from services.session import SessionState
from services.template_library import TemplateLibraryError, TemplateLibraryService


class TemplateLibraryDialog(QDialog):
    def __init__(
        self,
        library: TemplateLibraryService,
        session: SessionState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._session = session
        self._can_manage = has_permission(session.role, Permission.MANAGE_REPORT_TEMPLATES)
        self._can_use = self._can_manage or has_permission(
            session.role, Permission.USE_ACTIVE_REPORT_TEMPLATES
        )
        self.setObjectName("templateLibraryDialog")
        self.setWindowTitle("Библиотека шаблонов")
        self.setModal(True)
        self.setMinimumWidth(760)
        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self._active_only = QCheckBox("Только активные", objectName="templateActiveOnly")
        self._active_only.setChecked(True)
        self._active_only.toggled.connect(self._reload_templates)
        filters.addWidget(self._active_only)
        filters.addStretch(1)
        layout.addLayout(filters)

        self._templates = QTableWidget(objectName="templateLibraryTable")
        self._templates.setColumnCount(4)
        self._templates.setHorizontalHeaderLabels(
            ["Название", "Формат", "Архив", "Последняя версия"]
        )
        self._templates.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._templates.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._templates.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._templates.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._templates.itemSelectionChanged.connect(self._reload_versions)
        layout.addWidget(self._templates, stretch=1)

        self._versions = QTableWidget(objectName="templateVersionTable")
        self._versions.setColumnCount(3)
        self._versions.setHorizontalHeaderLabels(["Версия", "Режим", "Контракт"])
        self._versions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._versions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._versions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vheader = self._versions.horizontalHeader()
        assert vheader is not None
        vheader.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(QLabel("Версии выбранного шаблона"))
        layout.addWidget(self._versions, stretch=1)

        buttons = QHBoxLayout()
        self._upload_btn = QPushButton("Загрузить…", objectName="templateUploadBtn")
        self._archive_btn = QPushButton("В архив", objectName="templateArchiveBtn")
        self._restore_btn = QPushButton("Восстановить", objectName="templateRestoreBtn")
        self._generate_btn = QPushButton("Сформировать…", objectName="templateGenerateBtn")
        refresh_btn = QPushButton("Обновить", objectName="templateRefreshBtn")
        self._upload_btn.setEnabled(self._can_manage)
        self._archive_btn.setEnabled(self._can_manage)
        self._restore_btn.setEnabled(self._can_manage)
        self._generate_btn.setEnabled(self._can_use)
        self._upload_btn.clicked.connect(self._upload)
        self._archive_btn.clicked.connect(self._archive)
        self._restore_btn.clicked.connect(self._restore)
        self._generate_btn.clicked.connect(self._generate)
        refresh_btn.clicked.connect(self._reload_all)
        for btn in (
            self._upload_btn,
            self._archive_btn,
            self._restore_btn,
            self._generate_btn,
            refresh_btn,
        ):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._reload_all()

    def _reload_all(self) -> None:
        self._reload_templates()
        self._reload_versions()

    def _reload_templates(self) -> None:
        rows = self._library.list_templates(active_only=self._active_only.isChecked())
        self._templates.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._templates.setItem(i, 0, QTableWidgetItem(row.name))
            self._templates.setItem(i, 1, QTableWidgetItem(row.format))
            self._templates.setItem(
                i, 2, QTableWidgetItem("да" if row.is_archived else "нет")
            )
            latest = str(row.latest_version) if row.latest_version is not None else "—"
            item = QTableWidgetItem(latest)
            item.setData(256, row.id)  # Qt.ItemDataRole.UserRole
            self._templates.setItem(i, 3, item)
        if rows:
            self._templates.selectRow(0)
        else:
            self._versions.setRowCount(0)

    def _selected_template_id(self) -> int | None:
        row = self._templates.currentRow()
        if row < 0:
            return None
        item = self._templates.item(row, 3)
        if item is None:
            return None
        data = item.data(256)
        return int(data) if data is not None else None

    def _selected_version_id(self) -> int | None:
        row = self._versions.currentRow()
        if row < 0:
            return None
        item = self._versions.item(row, 0)
        if item is None:
            return None
        data = item.data(256)
        return int(data) if data is not None else None

    def _reload_versions(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            self._versions.setRowCount(0)
            return
        versions = self._library.list_versions(template_id)
        self._versions.setRowCount(len(versions))
        for i, ver in enumerate(versions):
            item = QTableWidgetItem(str(ver.version_number))
            item.setData(256, ver.id)
            self._versions.setItem(i, 0, item)
            self._versions.setItem(i, 1, QTableWidgetItem(ver.binding_mode))
            self._versions.setItem(i, 2, QTableWidgetItem(ver.contract_version))
        if versions:
            self._versions.selectRow(len(versions) - 1)

    def _upload(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите шаблон",
            "",
            "Шаблоны (*.xlsx *.xlsm *.pdf);;Все файлы (*)",
        )
        if not path_str:
            return
        source = Path(path_str)
        manifest_source: Path | None = None
        if source.suffix.lower() == ".pdf":
            manifest_str, _ = QFileDialog.getOpenFileName(
                self,
                "Сопутствующий manifest (.regions.json), если есть",
                str(source.parent),
                "JSON (*.json);;Все файлы (*)",
            )
            if manifest_str:
                manifest_source = Path(manifest_str)
        name, ok = _prompt_text(self, "Название шаблона", source.stem)
        if not ok or not name.strip():
            return
        try:
            self._library.upload_version(
                name=name.strip(), source=source, manifest_source=manifest_source
            )
        except (TemplateLibraryError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Загрузка шаблона", str(exc))
            return
        self._reload_all()

    def _archive(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            return
        try:
            self._library.archive_template(template_id)
        except (TemplateLibraryError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Архив", str(exc))
            return
        self._reload_all()

    def _restore(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            return
        try:
            self._library.restore_template(template_id)
        except (TemplateLibraryError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Восстановление", str(exc))
            return
        self._reload_all()

    def _generate(self) -> None:
        version_id = self._selected_version_id()
        if version_id is None:
            QMessageBox.information(self, "Формирование", "Выберите версию шаблона.")
            return
        row = self._templates.currentRow()
        fmt = "xlsx"
        if row >= 0:
            fmt_item = self._templates.item(row, 1)
            if fmt_item is not None and fmt_item.text() == "pdf":
                fmt = "pdf"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт",
            "",
            f"Отчёт (*.{fmt})",
        )
        if not path_str:
            return
        output = Path(path_str)
        if output.suffix.lower() != f".{fmt}":
            output = output.with_suffix(f".{fmt}")
        try:
            self._library.generate_report(version_id, output, values={})
        except (TemplateLibraryError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Формирование", str(exc))
            return
        QMessageBox.information(self, "Формирование", f"Отчёт сохранён:\n{output}")


def _prompt_text(parent: QWidget, title: str, default: str) -> tuple[str, bool]:
    from PySide6.QtWidgets import QInputDialog

    text, ok = QInputDialog.getText(parent, title, "Название:", text=default)
    return text, ok
