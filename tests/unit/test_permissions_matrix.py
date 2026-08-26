"""Матрица прав ТЗ §4.1 — параметризованные проверки."""

from __future__ import annotations

import pytest

from domain.permissions import Permission, RoleCode, has_permission, permissions_for


@pytest.mark.acceptance
@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (RoleCode.ADMINISTRATOR, Permission.MANAGE_ACCOUNTS, True),
        (RoleCode.ADMINISTRATOR, Permission.VIEW_USER_ACTION_LOG, True),
        (RoleCode.ADMINISTRATOR, Permission.RESTORE_BACKUP, True),
        (RoleCode.ADMINISTRATOR, Permission.MANAGE_REPORT_TEMPLATES, True),
        (RoleCode.ADMINISTRATOR, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS, True),
        (RoleCode.ADMINISTRATOR, Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS, True),
        (RoleCode.HR_EMPLOYEE, Permission.MANAGE_EMPLOYEES, True),
        (RoleCode.HR_EMPLOYEE, Permission.CREATE_BACKUP, True),
        (RoleCode.HR_EMPLOYEE, Permission.IMPORT_EXPORT, True),
        (RoleCode.HR_EMPLOYEE, Permission.MANAGE_ACCOUNTS, False),
        (RoleCode.HR_EMPLOYEE, Permission.VIEW_USER_ACTION_LOG, False),
        (RoleCode.HR_EMPLOYEE, Permission.RESTORE_BACKUP, False),
        (RoleCode.HR_EMPLOYEE, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS, False),
        (RoleCode.HR_EMPLOYEE, Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS, False),
        (RoleCode.OBSERVER, Permission.VIEW_EMPLOYEES, True),
        (RoleCode.OBSERVER, Permission.VIEW_STANDARD_REPORTS, True),
        (RoleCode.OBSERVER, Permission.MANAGE_EMPLOYEES, False),
        (RoleCode.OBSERVER, Permission.IMPORT_EXPORT, False),
        (RoleCode.OBSERVER, Permission.CREATE_BACKUP, False),
        (RoleCode.OBSERVER, Permission.MANAGE_ACCOUNTS, False),
    ],
)
def test_role_permission_matrix(role: RoleCode, permission: Permission, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed


def test_administrator_has_all_permissions() -> None:
    assert permissions_for(RoleCode.ADMINISTRATOR) == frozenset(Permission)


def test_sensitive_not_implied_by_hr_employee() -> None:
    perms = permissions_for(RoleCode.HR_EMPLOYEE)
    assert Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS not in perms
    assert Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS not in perms
