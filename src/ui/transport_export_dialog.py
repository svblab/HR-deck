"""EPIC-021 / Issue #130: HR transport package export UI."""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
from ui.package_delivery import (
    DeliveryResult,
    TrackedTemp,
    cleanup_tracked_temps,
    deliver_package,
    existing_tracked_paths,
    normalize_hrpkg_path,
    preflight_writable,
    unlink_quiet,
)

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


# Forbidden on FAT/exFAT removable media and invalid in paths:
# \ / : * ? " < > | and C0 controls (must not appear in suggestions).
_WIN_FILENAME_FORBIDDEN = re.compile(r'[\x00-\x1f\\/:*?"<>|]+')


def _default_export_filename(target: OutboundExportTarget) -> str:
    """Suggested .hrpkg name before package_id is known (path-first export)."""
    date = datetime.now(UTC).strftime("%Y%m%d")
    peer = _WIN_FILENAME_FORBIDDEN.sub("_", target.peer_label)
    peer = re.sub(r"[^\w\-]+", "_", peer, flags=re.UNICODE).strip("._")
    if not peer:
        peer = "peer"
    peer = peer[:48]
    return f"transport_{peer}_dir{target.direction_id}_{date}.hrpkg"


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
        self._preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
            label = f"{target.peer_label} (направление {target.direction_id}, статус: {status})"
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
                "Выбранное направление недоступно (статус «broken»). Обратитесь к администратору.",
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

    def _confirm_replace_normalized_path(self, save_path: Path) -> bool:
        """Ask before replacing a path that gained ``.hrpkg`` by normalization.

        Why: the existing file may be the only copy of an earlier undelivered
        transport package (DB already advanced). Silent overwrite would destroy it.
        When the dialog itself returned an existing ``*.hrpkg`` path, the native
        file dialog has already confirmed — do not ask twice.
        """
        answer = QMessageBox.question(
            self,
            "Экспорт данных",
            f"Файл {save_path} уже существует. Заменить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _choose_save_path(self, *, suggested: str) -> Path | None:
        """Path-first save dialog with overwrite check when suffix was appended."""
        while True:
            path, _filter = QFileDialog.getSaveFileName(
                self,
                "Сохранить transport-пакет",
                suggested,
                "Пакеты (*.hrpkg);;Все файлы (*.*)",
            )
            if not path:
                return None
            dialog_path = Path(path)
            save_path = normalize_hrpkg_path(dialog_path)
            # Suffix was appended and that target already exists → confirm.
            # Dialog returned an existing .hrpkg itself → native dialog already asked.
            if save_path != dialog_path and save_path.exists():
                if not self._confirm_replace_normalized_path(save_path):
                    continue
            return save_path

    def _ask_delivery_action(self, *, error: BaseException, save_path: Path) -> str:
        """Return ``retry``, ``relocate``, or ``abandon``."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Экспорт данных")
        box.setText(
            "Пакет уже сформирован в базе (состояние обмена продвинуто), "
            f"но файл не сохранён в «{save_path}»: {error}.\n\n"
            "Выберите действие. Повторный запуск экспорта создаст новый пакет "
            "с другим номером последовательности и может разорвать обмен."
        )
        retry_btn = box.addButton("Повторить", QMessageBox.ButtonRole.AcceptRole)
        relocate_btn = box.addButton("Выбрать другое место", QMessageBox.ButtonRole.ActionRole)
        abandon_btn = box.addButton("Отказаться", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is retry_btn:
            return "retry"
        if clicked is relocate_btn:
            return "relocate"
        if clicked is abandon_btn:
            return "abandon"
        return "abandon"

    def _confirm_abandon(self, tracked: list[TrackedTemp]) -> bool:
        detail = (
            "Состояние транспортного обмена уже продвинуто. "
            "Если отказаться сейчас, готового файла пакета не будет. "
            "НЕ запускайте экспорт повторно — это создаст новый пакет и может "
            "разорвать канал с получателем. Восстановление канала выполняет администратор."
        )
        leftover = existing_tracked_paths(tracked)
        if len(leftover) == 1:
            detail += (
                f"\n\nЕдинственная копия пакета осталась во временном файле:\n"
                f"{leftover[0].resolve()}\n"
                "Не удаляйте её до передачи администратору или до успешного сохранения."
            )
        elif len(leftover) > 1:
            lines = "\n".join(str(path.resolve()) for path in leftover)
            detail += (
                f"\n\nНа диске остались полные временные файлы — копии одного и того же "
                f"пакета:\n{lines}\n"
                "Ни один из них не следует удалять, пока пакет не будет доставлен."
            )
        answer = QMessageBox.question(
            self,
            "Отказаться от сохранения?",
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _show_abandon_final(self, tracked: list[TrackedTemp]) -> None:
        text = (
            "Сохранение отменено. Состояние обмена в базе уже изменено. "
            "Не выполняйте экспорт снова. Обратитесь к администратору для "
            "восстановления канала."
        )
        leftover = existing_tracked_paths(tracked)
        if len(leftover) == 1:
            text += (
                f"\n\nЕдинственная копия пакета осталась во временном файле:\n"
                f"{leftover[0].resolve()}\n"
                "Не удаляйте этот файл."
            )
        elif len(leftover) > 1:
            lines = "\n".join(str(path.resolve()) for path in leftover)
            text += (
                f"\n\nНа диске остались полные временные файлы — копии одного и того же "
                f"пакета:\n{lines}\n"
                "Ни один из них не следует удалять, пока пакет не будет доставлен."
            )
        QMessageBox.critical(self, "Экспорт данных", text)

    def _delivery_loop(self, wire_bytes: bytes, save_path: Path) -> Path | None:
        """
        Persist wire_bytes after DB export. Retry / relocate / confirmed abandon.

        Sequence: attempt → on failure show 3-button dialog → act on answer.
        Relocate-dialog cancel and abandon-confirmation No return to the dialog
        without a new delivery attempt. Returns final path or None on abandon.
        """
        tracked: list[TrackedTemp] = []
        current_path = save_path
        reuse_for_current: Path | None = None
        last_error: BaseException = RuntimeError("неизвестная ошибка сохранения файла")

        def run_attempt() -> Path | None:
            nonlocal reuse_for_current, last_error
            try:
                outcome = deliver_package(
                    wire_bytes,
                    current_path,
                    reuse_complete_temp=reuse_for_current,
                )
            except Exception as exc:  # noqa: BLE001 — never exit silently post-export
                outcome = DeliveryResult(complete_temp=reuse_for_current, error=exc)
            if outcome.error is not None:
                last_error = outcome.error
            if outcome.final_path is not None:
                cleanup_tracked_temps(tracked)
                return outcome.final_path
            if outcome.complete_temp is not None and outcome.complete_temp.is_file():
                already = any(
                    item.path.resolve() == outcome.complete_temp.resolve() for item in tracked
                )
                if not already:
                    tracked.append(
                        TrackedTemp(path=outcome.complete_temp, for_save_path=current_path)
                    )
                reuse_for_current = outcome.complete_temp
            return None

        # First attempt immediately after export (wrapped like later attempts).
        first = run_attempt()
        if first is not None:
            return first

        while True:
            action = self._ask_delivery_action(error=last_error, save_path=current_path)
            if action == "retry":
                done = run_attempt()
                if done is not None:
                    return done
                continue
            if action == "relocate":
                while True:
                    new_raw, _filter = QFileDialog.getSaveFileName(
                        self,
                        "Сохранить transport-пакет",
                        str(current_path),
                        "Пакеты (*.hrpkg);;Все файлы (*.*)",
                    )
                    if not new_raw:
                        break
                    dialog_path = Path(new_raw)
                    candidate = normalize_hrpkg_path(dialog_path)
                    if candidate != dialog_path and candidate.exists():
                        if not self._confirm_replace_normalized_path(candidate):
                            continue
                    current_path = candidate
                    # Never os.replace a temp from another filesystem into a new path
                    # (EXDEV); rewrite the bytes instead.
                    reuse_for_current = None
                    done = run_attempt()
                    if done is not None:
                        return done
                    break
                continue
            # abandon
            if not self._confirm_abandon(tracked):
                continue
            self._show_abandon_final(tracked)
            return None

    def _show_export_success(
        self,
        *,
        save_path: Path,
        package_id: str,
        sequence: int,
        generation: int,
        tables_exported: tuple[str, ...],
    ) -> None:
        self._last_result_path = save_path
        tables_note = ", ".join(tables_exported) if tables_exported else "(нет таблиц)"
        self._result_label.setText(
            "Экспорт завершён.\n"
            f"Файл: {save_path}\n"
            f"package_id: {package_id}\n"
            f"sequence: {sequence}, generation: {generation}\n"
            f"Таблицы: {tables_note}"
        )
        self._stack.setCurrentIndex(_PAGE_RESULT)

    def _run_export(self) -> None:
        target = self._selected_target()
        if target is None:
            return
        # 1) Empty-package confirmation before any DB export or path dialog.
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
        # 2) Choose save path before export so cancel never advances transport state.
        save_path = self._choose_save_path(suggested=_default_export_filename(target))
        if save_path is None:
            return
        # 3) Preflight: exclusive unique temp; never touch existing *.partial or final target.
        try:
            preflight_temp = preflight_writable(save_path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Экспорт данных",
                f"Не удалось подготовить файл для сохранения: {exc}",
            )
            return
        # 4) Export (service commit ordering unchanged — interim mitigation only).
        try:
            result = self._operator.export_personnel_package(target.direction_id)
        except Exception as exc:  # noqa: BLE001
            unlink_quiet(preflight_temp)
            QMessageBox.warning(self, "Экспорт данных", str(exc))
            return
        # Probe is no longer needed; delivery creates its own exclusive temps.
        unlink_quiet(preflight_temp)
        # 5) Delivery loop — DB has advanced; must not exit without success or confirmed abandon.
        final_path = self._delivery_loop(result.export.wire_bytes, save_path)
        if final_path is None:
            return
        self._show_export_success(
            save_path=final_path,
            package_id=result.export.package_id,
            sequence=result.export.sequence,
            generation=result.export.generation,
            tables_exported=result.tables_exported,
        )

    def _reset_to_select(self) -> None:
        self._preview_tables = {}
        self._last_result_path = None
        self._reload_targets()
        self._stack.setCurrentIndex(_PAGE_SELECT)


__all__ = ["TransportExportPanel"]
