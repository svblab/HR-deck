"""Централизованная матрица прав (ТЗ §4.1) и коды ролей."""

from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    ADMINISTRATOR = "administrator"
    HR_EMPLOYEE = "hr_employee"
    OBSERVER = "observer"


ROLE_IDS: dict[RoleCode, int] = {
    RoleCode.ADMINISTRATOR: 1,
    RoleCode.HR_EMPLOYEE: 2,
    RoleCode.OBSERVER: 3,
}


class Permission(StrEnum):
    """Явные идентификаторы разрешений — не размазывать `if role == ...` по UI."""

    MANAGE_ACCOUNTS = "manage_accounts"
    MANAGE_SECURITY_SETTINGS = "manage_security_settings"
    VIEW_USER_ACTION_LOG = "view_user_action_log"
    VIEW_TECHNICAL_EVENTS = "view_technical_events"

    MANAGE_EMPLOYEES = "manage_employees"
    VIEW_EMPLOYEES = "view_employees"
    MANAGE_STATUSES = "manage_statuses"
    VIEW_STATUSES = "view_statuses"
    MANAGE_DIRECTORIES = "manage_directories"
    VIEW_DIRECTORIES = "view_directories"

    IMPORT_EXPORT = "import_export"
    CREATE_BACKUP = "create_backup"
    RESTORE_BACKUP = "restore_backup"

    VIEW_STANDARD_REPORTS = "view_standard_reports"
    USE_ACTIVE_REPORT_TEMPLATES = "use_active_report_templates"
    MANAGE_REPORT_TEMPLATES = "manage_report_templates"

    # ANCHOR_CORE §2: не выдаются автоматически роли «Сотрудник HR».
    VIEW_SENSITIVE_EMPLOYEE_FIELDS = "view_sensitive_employee_fields"
    EDIT_SENSITIVE_EMPLOYEE_FIELDS = "edit_sensitive_employee_fields"


_ALL = frozenset(Permission)

_OBSERVER = frozenset(
    {
        Permission.VIEW_EMPLOYEES,
        Permission.VIEW_STATUSES,
        Permission.VIEW_DIRECTORIES,
        Permission.VIEW_STANDARD_REPORTS,
        Permission.USE_ACTIVE_REPORT_TEMPLATES,
    }
)

_HR = frozenset(
    {
        Permission.MANAGE_EMPLOYEES,
        Permission.VIEW_EMPLOYEES,
        Permission.MANAGE_STATUSES,
        Permission.VIEW_STATUSES,
        Permission.MANAGE_DIRECTORIES,
        Permission.VIEW_DIRECTORIES,
        Permission.IMPORT_EXPORT,
        Permission.CREATE_BACKUP,
        Permission.VIEW_STANDARD_REPORTS,
        Permission.USE_ACTIVE_REPORT_TEMPLATES,
        # Без MANAGE_ACCOUNTS, VIEW_USER_ACTION_LOG, RESTORE_BACKUP,
        # MANAGE_REPORT_TEMPLATES, sensitive fields (ТЗ §4.1 / ANCHOR_CORE §2).
    }
)

# ТЗ §4.1: Администратор — всё, включая учётные записи, безопасность, журналы,
# полное управление шаблонами и чувствительные поля.
ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    RoleCode.ADMINISTRATOR: _ALL,
    RoleCode.HR_EMPLOYEE: _HR,
    RoleCode.OBSERVER: _OBSERVER,
}


def permissions_for(role: RoleCode | str) -> frozenset[Permission]:
    code = RoleCode(role)
    return ROLE_PERMISSIONS[code]


def has_permission(role: RoleCode | str, permission: Permission) -> bool:
    return permission in permissions_for(role)
