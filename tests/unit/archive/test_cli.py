import pytest

from backend.archive.runner.cli import load_brands, main

YML = """
brands:
  - domain: kuurth.com
    homepage_url: https://kuurth.com
  - domain: coltmcr.com
    homepage_url: https://coltmcr.com
    notes: password-gated as of 2026-08-26
"""


@pytest.mark.unit
def test_load_brands(tmp_path):
    p = tmp_path / "brands.yml"
    p.write_text(YML)
    brands = load_brands(p)
    assert [b.domain for b in brands] == ["kuurth.com", "coltmcr.com"]
    assert brands[1].notes.startswith("password-gated")


@pytest.mark.unit
def test_status_on_an_empty_store_lists_seeded_brands(tmp_path, capsys):
    p = tmp_path / "brands.yml"
    p.write_text(YML)
    objects = tmp_path / "objects"
    # --objects, not R2: an explicit path is what keeps a test off the real bucket.
    code = main(["status", "--objects", str(objects), "--brands", str(p)])
    out = capsys.readouterr().out
    assert code == 0
    assert "kuurth.com" in out and "coltmcr.com" in out and "BRAND" in out
