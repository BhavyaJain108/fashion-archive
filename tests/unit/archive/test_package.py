import pytest


@pytest.mark.unit
def test_archive_package_imports():
    import backend.archive  # noqa: F401


@pytest.mark.unit
def test_archive_does_not_import_legacy_packages():
    """The new body must stand alone (spec §3.2 / Global Constraints)."""
    import sys

    import backend.archive  # noqa: F401

    forbidden = [m for m in sys.modules if m.startswith(("scraper", "stages", "prod_page_v2"))]
    assert forbidden == []
