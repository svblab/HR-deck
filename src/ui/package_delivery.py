"""Qt-free filesystem delivery helpers for transport .hrpkg export (Issue #130)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

_RETRY_PARTIAL_ALLOCATIONS = 32


@dataclass
class DeliveryResult:
    """Outcome of one filesystem delivery attempt after DB export."""

    final_path: Path | None = None
    complete_temp: Path | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class TrackedTemp:
    """A complete (fsynced) temp kept for recovery; tied to one intended target."""

    path: Path
    for_save_path: Path


def normalize_hrpkg_path(path: Path) -> Path:
    """Ensure the filename ends with ``.hrpkg`` without replacing other suffixes.

    If the name already ends with ``.hrpkg`` (case-insensitive), leave it unchanged.
    Otherwise append ``.hrpkg`` to the full name (``out.txt`` → ``out.txt.hrpkg``).
    """
    if path.name.lower().endswith(".hrpkg"):
        return path
    return path.with_name(path.name + ".hrpkg")


def new_unique_partial(save_path: Path) -> Path:
    """Sibling temp path: ``<final>.<8 hex>.partial`` (never a bare ``.partial``)."""
    return Path(f"{save_path}.{secrets.token_hex(4)}.partial")


def unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _fsync_parent_dir(path: Path) -> None:
    """Best-effort directory fsync after creating or renaming a file (POSIX durability)."""
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def preflight_writable(save_path: Path) -> Path:
    """
    Prove the target directory is writable via an exclusive empty temp file.

    Uses open(..., "xb") so an existing *.partial is never truncated.
    Returns the created temp path. Caller must remove it (success or export failure).
    Raises OSError if preflight cannot complete.
    """
    last_error: OSError | None = None
    for _ in range(_RETRY_PARTIAL_ALLOCATIONS):
        partial = new_unique_partial(save_path)
        try:
            # "xb": exclusive create; mode bits follow umask like a normal create.
            with open(partial, "xb") as probe:
                probe.write(b"")
                probe.flush()
                os.fsync(probe.fileno())
            return partial
        except FileExistsError:
            continue
        except OSError as exc:
            unlink_quiet(partial)
            last_error = exc
            break
    if last_error is not None:
        raise last_error
    raise OSError("не удалось создать уникальный временный файл для проверки записи")


def deliver_package(
    wire_bytes: bytes,
    save_path: Path,
    *,
    reuse_complete_temp: Path | None = None,
) -> DeliveryResult:
    """
    Atomically place ``wire_bytes`` at ``save_path``.

    ``reuse_complete_temp`` may be used **only** when it was created for this
    same ``save_path`` (caller responsibility). Then only ``os.replace`` is
    retried. On relocate / new target, caller must pass ``reuse_complete_temp=None``
    so bytes are written to a fresh exclusive temp next to the new path.

    On failure: incomplete temps are deleted; complete temps are kept.
    """
    if reuse_complete_temp is not None and reuse_complete_temp.is_file():
        try:
            os.replace(reuse_complete_temp, save_path)
            _fsync_parent_dir(save_path)
            return DeliveryResult(final_path=save_path)
        except Exception as exc:  # noqa: BLE001
            return DeliveryResult(complete_temp=reuse_complete_temp, error=exc)

    partial: Path | None = None
    write_complete = False
    try:
        handle = None
        for _ in range(_RETRY_PARTIAL_ALLOCATIONS):
            candidate = new_unique_partial(save_path)
            try:
                handle = open(candidate, "xb")
                partial = candidate
                break
            except FileExistsError:
                continue
        if handle is None or partial is None:
            raise OSError("не удалось создать уникальный временный файл для записи пакета")
        try:
            with handle:
                handle.write(wire_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            write_complete = True
            _fsync_parent_dir(partial)
            os.replace(partial, save_path)
            _fsync_parent_dir(save_path)
            return DeliveryResult(final_path=save_path)
        except Exception:
            if not write_complete:
                unlink_quiet(partial)
                partial = None
            raise
    except Exception as exc:  # noqa: BLE001
        kept = partial if write_complete and partial is not None else None
        return DeliveryResult(complete_temp=kept, error=exc)


def cleanup_tracked_temps(tracked: list[TrackedTemp]) -> None:
    """Best-effort delete of temps tracked during a delivery loop (after success)."""
    for item in tracked:
        unlink_quiet(item.path)


def existing_tracked_paths(tracked: list[TrackedTemp]) -> list[Path]:
    return [item.path for item in tracked if item.path.is_file()]


__all__ = [
    "DeliveryResult",
    "TrackedTemp",
    "cleanup_tracked_temps",
    "deliver_package",
    "existing_tracked_paths",
    "new_unique_partial",
    "normalize_hrpkg_path",
    "preflight_writable",
    "unlink_quiet",
]
