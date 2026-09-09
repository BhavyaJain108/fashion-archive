import subprocess
import sys

import pytest


@pytest.mark.unit
def test_archive_package_imports():
    import backend.archive  # noqa: F401


@pytest.mark.unit
def test_archive_does_not_import_legacy_packages():
    """The new body must stand alone (spec §3.2 / Global Constraints).

    Asked in a clean interpreter, because sys.modules is global: reading it inside the
    suite answers "did anything in this repo import the old packages", which any legacy
    test makes true, rather than "does backend.archive".
    """
    probe = (
        "import sys, backend.archive;"
        "print([m for m in sys.modules"
        " if m.startswith(('scraper', 'stages', 'prod_page_v2'))])"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", f"backend.archive pulled in {out.stdout.strip()}"
