"""EPIC-021 / Issue #130: HR transport package export UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.transport import DirectionStatus
from services.session import SessionState
from services.transport_operator import OutboundExportTarget, TransportOperatorService

_PAGE_SELECT = 0
_PAGE_PREVIEW = 1
_PAGE_RESULT = 2


def _format_preview_counts(tables: dict[str, list]) -> str:
    if not tables:
        return "Нет изменений с последнего экспорта (пустой business payload)."
    lines = ["Таблицы в пакете:"]
    for name in sorted(tables):
        lines.append(f"  • {name}: {len(tables[name])} строк")
    return "\n".join(lines)


class TransportExportPanel(QWidget):
    """Export flow: choose outbound direction → preview → save .hrpkg file."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("transportExportPanel")
        self._conn = conn
        self._session = session
        self._operator = TransportOperatorService(conn, session)
        self._targets: list[OutboundExportTarget] = []
        self._preview_tables: dict[str, list] = {}
        self._last_result_path: Path | None = None

        root = QVBoxLayout(self)
        self._stack = QStackedWidget(objectName="transportExportStack")
        root.addWidget(self._stack, stretch=1)
        self._stack.addWidget(self._build_select_page())
        self._stack.addWidget(self._build_preview_page())
        self._stack.addWidget(self._build_result_page())
        self._reload_targets()

    def _build_select_page(self) -> QWidget:
        page = QWidget(objectName="transportExportSelectPage")
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "Сформируйте transport-пакет для отправки другой установке. "
                "Направление обмена настраивает администратор; здесь только "
                "экспорт данных при уже установленном доверии."
            )
        )
        self._direction_combo = QComboBox(objectName="transportExportDirectionCombo")
        layout.addWidget(self._direction_combo)
        self._select_status = QLabel(objectName="transportExportSelectStatus")
        self._select_status.setWordWrap(True)
        layout.addWidget(self._select_status)
        row = QHBoxLayout()
        refresh = QPushButton("Обновить список", objectName="transportExportRefreshBtn")
        refresh.clicked.connect(self._reload_targets)
        row.addWidget(refresh)
        next_btn = QPushButton("Далее…", objectName="transportExportNextBtn")
        next_btn.clicked.connect(self._go_preview)
        row.addWidget(next_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget(objectName="transportExportPreviewPage")
        layout = QVBoxLayout(page)
        self._preview_label = QLabel(objectName="transportExportPreviewLabel")
        self._preview_label.setWordWrap(True)
        self._preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._preview_label)
        row = QHBoxLayout()
        back = QPushButton("Назад", objectName="transportExportBackBtn")
        back.clicked.connect(lambda: self._stack.setCurrentIndex(_PAGE_SELECT))
        row.addWidget(back)
        self._export_btn = QPushButton(
            "Сформировать и сохранить…", objectName="transportExportSaveBtn"
        )
        self._export_btn.clicked.connect(self._run_export)
        row.addWidget(self._export_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget(objectName="transportExportResultPage")
        layout = QVBoxLayout(page)
        self._result_label = QLabel(objectName="transportExportResultLabel")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)
        again = QPushButton("Новый экспорт", objectName="transportExportAgainBtn")
        again.clicked.connect(self._reset_to_select)
        layout.addWidget(again)
        layout.addStretch(1)
        return page

    def _reload_targets(self) -> None:
        self._direction_combo.clear()
        try:
            self._targets = self._operator.list_outbound_export_targets()
        except Exception as exc:  # noqa: BLE001
            self._targets = []
            self._select_status.setText(f"Не удалось загрузить направления: {exc}")
            return
        if not self._targets:
            self._select_status.setText(
                "Нет исходящих направлений обмена. Обратитесь к администратору "
                "для настройки доверия и направления."
            )
            return
        for target in self._targets:
            status = target.direction_status.value
            label = (
                f"{target.peer_label} (направление {target.direction_id}, "
                f"статус: {status})"
            )
            self._direction_combo.addItem(label, target.direction_id)
        self._select_status.setText(
            f"Доступно направлений: {len(self._targets)}. Выберите получателя."
        )

    def _selected_target(self) -> OutboundExportTarget | None:
        idx = self._direction_combo.currentIndex()
        if idx < 0 or idx >= len(self._targets):
            return None
        return self._targets[idx]

    def _go_preview(self) -> None:
        target = self._selected_target()
        if target is None:
            QMessageBox.information(
                self,
                "Экспорт данных",
                "Выберите направление обмена или обратитесь к администратору.",
            )
            return
        if target.direction_status is DirectionStatus.BROKEN:
            QMessageBox.warning(
                self,
                "Экспорт данных",
                "Выбранное направление недоступно (статус «broken»). "
                "Обратитесь к администратору.",
            )
            return
        try:
            from services.directory_sync import DirectorySyncService

            sync = DirectorySyncService(self._conn, self._session)
            pkg = sync.build_export_package(target.direction_id)
            self._preview_tables = pkg.tables
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Экспорт данных", str(exc))
            return
        self._preview_label.setText(
            f"Получатель: {target.peer_label}\n"
            f"Направление: {target.direction_id}\n"
            f"Поколение: {target.generation}, принято пакетов: {target.accepted_sequence}\n\n"
            f"{_format_preview_counts(self._preview_tables)}\n\n"
            "При пустом пакете будет отправлен только служебный transport-контейнер "
            "(без изменения справочников/сотрудников)."
        )
        self._export_btn.setEnabled(True)
        self._stack.setCurrentIndex(_PAGE_PREVIEW)

    def _run_export(self) -> None:
        target = self._selected_target()
        if target is None:
            return
        if not self._preview_tables:
            confirm = QMessageBox.question(
                self,
                "Экспорт данных",
                "С последнего экспорта изменений не обнаружено. "
                "Всё равно сформировать transport-пакет?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self._operator.export_personnel_package(target.direction_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Экспорт данных", str(exc))
            return
        default_name = f"{result.export.package_id}.hrpkg"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Сохранить transport-пакет",
            default_name,
            "Пакеты (*.hrpkg);;Все файлы (*.*)",
        )
        if not path:
            QMessageBox.information(
                self,
                "Экспорт данных",
                "Пакет сформирован, но файл не сохранён (отмена выбора пути).",
            )
            return
        save_path = Path(path)
        if save_path.suffix.lower() != ".hrpkg":
            save_path = save_path.with_suffix(".hrpkg")
        try:
            save_path.write_bytes(result.export.wire_bytes)
        except OSError as exc:
            QMessageBox.warning(self, "Экспорт данных", f"Не удалось записать файл: {exc}")
            return
        self._last_result_path = save_path
        tables_note = (
            ", ".join(result.tables_exported) if result.tables_exported else "(нет таблиц)"
        )
        self._result_label.setText(
            "Экспорт завершён.\n"
            f"Файл: {save_path}\n"
            f"package_id: {result.export.package_id}\n"
            f"sequence: {result.export.sequence}, generation: {result.export.generation}\n"
            f"Таблицы: {tables_note}"
        )
        self._stack.setCurrentIndex(_PAGE_RESULT)

    def _reset_to_select(self) -> None:
        self._preview_tables = {}
        self._last_result_path = None
        self._reload_targets()
        self._stack.setCurrentIndex(_PAGE_SELECT)


__all__ = ["TransportExportPanel"]
