import pytest

from backend.archive.runner import cli
from backend.archive.runner.cli import load_brands, main
from tests.unit.archive.test_end_to_end import mock_transport  # noqa: E402

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


@pytest.mark.unit
def test_a_scrape_fetches_the_photographs_too(tmp_path, monkeypatch, capsys):
    """Images come with the catalogue by default. Two commands meant the records could
    drift into being links to other people's servers, which is the thing the archive
    exists not to be."""
    called: list[list[str]] = []

    import backend.archive.runner.archive_images as pass_module

    monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: mock_transport())
    monkeypatch.setattr(pass_module, "outstanding", lambda cat, domain: 3)
    monkeypatch.setattr(
        pass_module,
        "archive_all",
        lambda domains, *a, **k: called.append(list(domains)) or [],
    )

    brands = tmp_path / "brands.yml"
    brands.write_text(YML)
    code = cli.main(
        [
            "scrape",
            "kuurth.com",
            "--full",
            "--objects",
            str(tmp_path / "objects"),
            "--brands",
            str(brands),
            "--locks",
            str(tmp_path / "locks"),
            "--logs",
            str(tmp_path / "logs"),
        ]
    )
    assert code == 0
    assert called == [["kuurth.com"]], "the image pass did not run"


@pytest.mark.unit
def test_no_images_skips_the_pass(tmp_path, monkeypatch):
    called: list[list[str]] = []

    import backend.archive.runner.archive_images as pass_module

    monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: mock_transport())
    monkeypatch.setattr(pass_module, "outstanding", lambda cat, domain: 3)
    monkeypatch.setattr(
        pass_module, "archive_all", lambda domains, *a, **k: called.append(list(domains)) or []
    )

    brands = tmp_path / "brands.yml"
    brands.write_text(YML)
    cli.main(
        [
            "scrape",
            "kuurth.com",
            "--full",
            "--no-images",
            "--objects",
            str(tmp_path / "objects"),
            "--brands",
            str(brands),
            "--locks",
            str(tmp_path / "locks"),
            "--logs",
            str(tmp_path / "logs"),
        ]
    )
    assert called == []
