"""Documentation sync and smoke tests (EPIC-017)."""

from __future__ import annotations

from pathlib import Path

from domain.template_markers import marker_catalog_markdown

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "docs" / "manual"
PROMO = ROOT / "docs" / "promo"


def test_report_templates_guide_marker_catalog_in_sync() -> None:
    guide = (ROOT / "docs/report-templates-guide.md").read_text(encoding="utf-8")
    assert marker_catalog_markdown() in guide


def test_report_templates_guide_has_limitations_and_parameters() -> None:
    guide = (ROOT / "docs/report-templates-guide.md").read_text(encoding="utf-8")
    assert "## 7. Поддерживаемые возможности и ограничения" in guide
    assert "password-protected pdf" in guide
    assert "## 8. Параметры при генерации" in guide
    assert "values={}" in guide


def test_deployment_guide_matches_packaging_paths() -> None:
    deployment = (MANUAL / "deployment-guide.md").read_text(encoding="utf-8")
    packaging = (ROOT / "packaging/README.md").read_text(encoding="utf-8")
    for fragment in (
        "/opt/personnel-availability/venv/",
        "personnel-availability",
        "PERSONNEL_AVAILABILITY_DATA",
        "backups/",
        "templates/",
        "logs/",
    ):
        assert fragment in deployment
        assert fragment in packaging


def test_documentation_package_files_exist() -> None:
    for name in (
        "user-guide.md",
        "administrator-guide.md",
        "deployment-guide.md",
        "maintenance-runbook.md",
        "install-update-quick.md",
        "quick-reference.md",
    ):
        assert (MANUAL / name).is_file()
    assert (PROMO / "product-booklet.md").is_file()
