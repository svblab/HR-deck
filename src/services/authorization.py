"""Авторизация: проверка Permission по роли текущей сессии."""

from __future__ import annotations

from domain.permissions import Permission, RoleCode, has_permission


class AuthorizationError(PermissionError):
    """Отказ в доступе на уровне сервиса (не UI)."""


class AuthorizationService:
    """Единая точка проверки прав — UI только скрывает контролы."""

    def require(self, role: RoleCode | str, permission: Permission) -> None:
        if not has_permission(role, permission):
            raise AuthorizationError(f"permission denied: {permission.value}")

    def check(self, role: RoleCode | str, permission: Permission) -> bool:
        return has_permission(role, permission)
