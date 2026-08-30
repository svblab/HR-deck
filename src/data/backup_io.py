"""Копирование и проверка файлов БД/keywrap для резервного копирования (EPIC-012)."""

from __future__ import annotations

from pathlib import Path

from data.db import (
    Connection,
    DatabaseError,
    IntegrityError,
    connect,
    file_looks_unencrypted,
)
from data.keywrap import keywrap_path_for


class DatabaseCorruptionError(DatabaseError):
    """Файл БД повреждён или записан не полностью."""


def default_backups_dir(data_dir: Path | None = None) -> Path:
    from data.paths import default_backups_dir as _default_backups_dir

    return _default_backups_dir(data_dir)


def backup_filename(clock_iso: str) -> str:
    safe = clock_iso.replace(":", "").replace("-", "")
    return f"personnel-{safe}.db"


def atomic_copy_file(source: Path, destination: Path) -> None:
    """Запись через `.partial` + replace — не оставлять полуфайл на месте назначения."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    partial.write_bytes(source.read_bytes())
    partial.replace(destination)


def copy_database_pair(source_db: Path, destination_db: Path) -> None:
    """Скопировать SQLCipher-файл и sidecar keywrap (ADR-0003)."""
    atomic_copy_file(source_db, destination_db)
    atomic_copy_file(keywrap_path_for(source_db), keywrap_path_for(destination_db))


def verify_database_file(db_path: Path, master_key: bytes) -> None:
    """Открыть бэкап/БД мастер-ключом: cipher_integrity_check + PRAGMA integrity_check."""
    conn = connect(db_path, master_key, check_integrity=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            raise IntegrityError(f"integrity_check failed: {row!r}")
    finally:
        conn.close()


def checkpoint_wal(conn: Connection) -> None:
    conn.execute("PRAGMA wal_checkpoint(FULL)")


def _unlink_if_exists(path: Path) -> None:
    if path.is_file():
        path.unlink()


def cleanup_stale_partial_files(db_path: Path) -> list[str]:
    """Удалить `.partial` от прерванной atomic-copy; вернуть описание действий."""
    actions: list[str] = []
    parent = db_path.parent
    patterns = (
        db_path.name + ".partial",
        keywrap_path_for(db_path).name + ".partial",
    )
    for name in patterns:
        partial = parent / name
        if partial.is_file():
            partial.unlink()
            actions.append(f"removed stale partial file {partial.name}")
    return actions


def recover_interrupted_restore(db_path: Path) -> list[str]:
    """
    После сбоя restore: убрать partial-файлы; если live повреждён — откат из .pre-restore.bak.
    """
    actions = cleanup_stale_partial_files(db_path)
    bak_db = db_path.with_suffix(db_path.suffix + ".pre-restore.bak")
    bak_kw = Path(str(keywrap_path_for(db_path)) + ".pre-restore.bak")
    live_ok = _probe_database_file(db_path)
    if live_ok:
        if bak_db.is_file():
            _unlink_if_exists(bak_db)
            _unlink_if_exists(bak_kw)
            actions.append("removed stale pre-restore backups")
        return actions
    if bak_db.is_file() and bak_kw.is_file():
        if db_path.is_file():
            db_path.unlink()
        bak_db.replace(db_path)
        kw_path = keywrap_path_for(db_path)
        if kw_path.is_file():
            kw_path.unlink()
        bak_kw.replace(kw_path)
        actions.append("restored live database from pre-restore backup")
    return actions


def prepare_database_startup(db_path: Path) -> list[str]:
    """
    Перед входом: очистка partial-файлов и явная ошибка при явно битом файле БД.
    """
    actions = recover_interrupted_restore(db_path)
    if not db_path.is_file():
        return actions
    size = db_path.stat().st_size
    if size < 512:
        raise DatabaseCorruptionError(
            "Файл базы данных повреждён или записан не полностью "
            f"({db_path}, {size} bytes). Восстановите из резервной копии."
        )
    if file_looks_unencrypted(db_path):
        raise DatabaseCorruptionError(
            "Файл базы данных не похож на зашифрованную SQLCipher-базу. "
            "Проверьте путь или восстановите из резервной копии."
        )
    return actions


def _probe_database_file(db_path: Path) -> bool:
    if not db_path.is_file() or db_path.stat().st_size < 512:
        return False
    if file_looks_unencrypted(db_path):
        return False
    return True


def swap_live_from_backup(live_db: Path, backup_db: Path) -> None:
    """
    Атомарная замена live db+keywrap проверенной парой из бэкапа.
    Сначала сохраняет текущие файлы как `.pre-restore.bak`.
    """
    live_kw = keywrap_path_for(live_db)
    backup_kw = keywrap_path_for(backup_db)
    if not backup_db.is_file() or not backup_kw.is_file():
        raise DatabaseError("backup database or keywrap not found")

    bak_db = live_db.with_suffix(live_db.suffix + ".pre-restore.bak")
    bak_kw = Path(str(live_kw) + ".pre-restore.bak")

    if live_db.is_file():
        if bak_db.is_file():
            bak_db.unlink()
        live_db.replace(bak_db)
    if live_kw.is_file():
        if bak_kw.is_file():
            bak_kw.unlink()
        live_kw.replace(bak_kw)

    try:
        copy_database_pair(backup_db, live_db)
    except Exception:
        _rollback_from_pre_restore(live_db, bak_db, bak_kw)
        raise

    _unlink_if_exists(bak_db)
    _unlink_if_exists(bak_kw)


def _rollback_from_pre_restore(live_db: Path, bak_db: Path, bak_kw: Path) -> None:
    _unlink_if_exists(live_db)
    _unlink_if_exists(keywrap_path_for(live_db))
    if bak_db.is_file():
        bak_db.replace(live_db)
    if bak_kw.is_file():
        bak_kw.replace(keywrap_path_for(live_db))


def remove_paths(*paths: Path) -> None:
    for path in paths:
        _unlink_if_exists(path)
