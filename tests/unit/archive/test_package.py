import subprocess
import sys

import pytest


@pytest.mark.unit
def test_archive_package_imports():
    import backend.archive  # noqa: F401


@pytest.mark.unit
def test_archive_does_not_import_the_web_layer():
    """The archive is a library and a CLI. It must not drag in the app.

    This used to assert it imported nothing from scraper/, stages/ or prod_page_v2/.
    Those are deleted, so that assertion can no longer fail and stopped being a test.
    The live version of the same constraint is that the scraper runs wherever it likes
    — a laptop, a worker, a cron — and pulling Flask in through an accidental import
    would tie it to the server it is deliberately kept separate from.

    Asked in a clean interpreter, because sys.modules is global: read inside the suite
    it would answer "did anything in this repo import Flask", which the API tests make
    true, rather than "does backend.archive".
    """
    probe = (
        "import sys, backend.archive, backend.archive.runner.cli;"
        "print([m for m in sys.modules if m.split('.')[0] in ('flask', 'werkzeug')])"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", f"backend.archive pulled in {out.stdout.strip()}"
