"""Home branch identity for directory sync export scoping (ADR-0007 addendum)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.accounts import SettingsRepository
from data.db import Connection
from data.directories import BranchRecord, BranchRepository
from data.repositories import TechnicalEventRepository
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.directories import DirectoryService
from services.session import SessionState

Clock = Callable[[], str]

HOME_BRANCH_EXTERNAL_ID_KEY = "home_branch_external_id"


class InstallationIdentityError(Exception):
    """Base error for installation identity operations."""


class HomeBranchNotSetError(InstallationIdentityError):
    """Raised when home branch is required but not configured."""

    def __init__(self) -> None:
        super().__init__(
            "Домашний филиал не задан. Обратитесь к администратору."
        )


class InstallationIdentityAlreadySetError(InstallationIdentityError):
    """Raised when home branch was already configured."""

    def __init__(self) -> None:
        super().__init__("Домашний филиал уже задан и не может быть изменён.")


class InvalidHomeBranchRequestError(InstallationIdentityError):
    """Raised when set_home_branch arguments are invalid."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InstallationIdentityService:
    """Read and one-time set of the installation home branch."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        directories: DirectoryService | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._settings = SettingsRepository(conn)
        self._branches = BranchRepository(conn)
        self._directories = directories or DirectoryService(
            conn, session, authz=self._authz, clock=self._clock
        )
        self._events = TechnicalEventRepository(conn)

    def get_home_branch(self) -> BranchRecord | None:
        external_id = self._settings.get(HOME_BRANCH_EXTERNAL_ID_KEY)
        if external_id is None:
            return None
        return self._branches.get_by_external_id(external_id)

    def require_home_branch(self) -> BranchRecord:
        branch = self.get_home_branch()
        if branch is None:
            raise HomeBranchNotSetError()
        return branch

    def set_home_branch(
        self,
        *,
        existing_branch_id: int | None = None,
        new_branch_name: str | None = None,
    ) -> BranchRecord:
        self._authz.require(
            self._session.role, Permission.MANAGE_INSTALLATION_IDENTITY
        )
        if self.get_home_branch() is not None:
            raise InstallationIdentityAlreadySetError()
        has_existing = existing_branch_id is not None
        has_new_name = new_branch_name is not None
        if has_existing == has_new_name:
            raise InvalidHomeBranchRequestError(
                "Укажите либо существующий филиал, либо имя нового филиала."
            )

        if has_new_name:
            name = new_branch_name
            assert name is not None
            clean_name = name.strip()
            if not clean_name:
                raise InvalidHomeBranchRequestError("Имя филиала не может быть пустым.")
            branch_id = self._directories.create_branch(clean_name)
            branch = self._branches.get(branch_id)
        else:
            assert existing_branch_id is not None
            branch = self._branches.get(existing_branch_id)
        if branch is None:
            raise InvalidHomeBranchRequestError("Филиал не найден.")

        now = self._clock()
        self._settings.set(HOME_BRANCH_EXTERNAL_ID_KEY, branch.external_id)
        self._events.record(
            event_type="installation.home_branch.set",
            message=f"external_id={branch.external_id} name={branch.name}",
            created_at=now,
        )
        self._conn.commit()
        return branch
