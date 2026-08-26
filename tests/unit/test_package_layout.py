"""Пакеты слоёв из ANCHOR_CORE §5 существуют и импортируются."""

import data
import domain
import reports
import services
import ui


def test_layer_packages_importable() -> None:
    assert domain.__doc__
    assert data.__doc__
    assert services.__doc__
    assert reports.__doc__
    assert ui.__doc__
