"""Unit tests for the LLM fixture recorder.

The recorder is load-bearing for Phase 1 of the cheap-model migration: it
produces the frozen baseline that every future eval measures against. These
tests cover the pure logic (hashing, enable flag, filename conventions) plus
the file-writing behaviour against a tmp_path so there's no real LLM in the
loop.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from scraper.llm_recorder import (
    FixtureRecorder,
    compute_fixture_id,
    is_recording_enabled,
)


@pytest.mark.unit
class TestIsRecordingEnabled:
    def test_unset_means_disabled(self, monkeypatch):
        monkeypatch.delenv("LLM_RECORD", raising=False)
        assert is_recording_enabled() is False

    def test_zero_means_disabled(self, monkeypatch):
        monkeypatch.setenv("LLM_RECORD", "0")
        assert is_recording_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "True", "YES", "on"])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.setenv("LLM_RECORD", value)
        assert is_recording_enabled() is True


@pytest.mark.unit
class TestComputeFixtureId:
    def test_same_prompt_same_id(self):
        assert compute_fixture_id("hello") == compute_fixture_id("hello")

    def test_different_prompts_different_ids(self):
        assert compute_fixture_id("hello") != compute_fixture_id("world")

    def test_twelve_hex_chars(self):
        fid = compute_fixture_id("any prompt")
        assert len(fid) == 12
        assert all(c in "0123456789abcdef" for c in fid)

    def test_image_changes_id(self):
        """Same prompt but different image → different fixture id.
        Critical: otherwise vision calls with the same prompt would collide."""
        b64_a = base64.b64encode(b"image-bytes-a").decode()
        b64_b = base64.b64encode(b"image-bytes-b").decode()
        assert compute_fixture_id("p", b64_a) != compute_fixture_id("p", b64_b)
        assert compute_fixture_id("p", b64_a) == compute_fixture_id("p", b64_a)


@pytest.mark.unit
class TestFixtureRecorder:
    def test_records_successful_json_call(self, tmp_path: Path):
        rec = FixtureRecorder(base_dir=tmp_path)
        rec.record_call(
            method="call",
            prompt="classify these links",
            output={
                "success": True,
                "data": {"label": "product"},
                "latency_ms": 123.4,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
            operation="url_classification",
            stage="urls",
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            response_model="LinkClassification",
            brand="khaite.com",
        )

        target_dir = tmp_path / "urls" / "url_classification"
        files = list(target_dir.glob("khaite_com_*.json"))
        assert len(files) == 1

        fixture = json.loads(files[0].read_text())
        assert fixture["method"] == "call"
        assert fixture["operation"] == "url_classification"
        assert fixture["stage"] == "urls"
        assert fixture["brand"] == "khaite.com"
        assert fixture["input"]["prompt"] == "classify these links"
        assert fixture["input"]["response_model"] == "LinkClassification"
        assert fixture["input"]["image_ref"] is None
        assert fixture["output"]["success"] is True
        assert fixture["output"]["data"] == {"label": "product"}

    def test_skips_failed_calls(self, tmp_path: Path):
        """Failed calls (transient 429s, validation errors) aren't ground
        truth — never record them."""
        rec = FixtureRecorder(base_dir=tmp_path)
        rec.record_call(
            method="call",
            prompt="anything",
            output={"success": False, "error": "timeout"},
            operation="whatever",
            stage="urls",
            model="claude-sonnet-4-20250514",
            max_tokens=100,
        )
        assert list(tmp_path.rglob("*.json")) == []

    def test_same_input_overwrites(self, tmp_path: Path):
        """Idempotent: re-running same input writes to same file."""
        rec = FixtureRecorder(base_dir=tmp_path)
        payload = dict(
            method="call",
            prompt="same prompt",
            output={
                "success": True,
                "data": {"x": 1},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            operation="op",
            stage="urls",
            model="m",
            max_tokens=100,
            brand="b.com",
        )
        rec.record_call(**payload)
        rec.record_call(**payload)

        files = list(tmp_path.rglob("b_com_*.json"))
        assert len(files) == 1  # overwritten

        # index appends every call, so we have evidence both happened
        index_lines = (tmp_path / "index.jsonl").read_text().strip().splitlines()
        assert len(index_lines) == 2

    def test_different_prompts_produce_different_fixtures(self, tmp_path: Path):
        rec = FixtureRecorder(base_dir=tmp_path)
        for prompt in ("prompt A", "prompt B"):
            rec.record_call(
                method="call",
                prompt=prompt,
                output={
                    "success": True,
                    "data": {},
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
                operation="op",
                stage="urls",
                model="m",
                max_tokens=100,
                brand="b.com",
            )
        files = list(tmp_path.rglob("b_com_*.json"))
        assert len(files) == 2

    def test_records_vision_call_with_image_file(self, tmp_path: Path):
        rec = FixtureRecorder(base_dir=tmp_path)
        png_bytes = b"\x89PNG\r\n\x1a\nfake-png-payload"
        b64 = base64.b64encode(png_bytes).decode()

        rec.record_call(
            method="call_with_image",
            prompt="describe this nav",
            output={
                "success": True,
                "response": "looks like a hamburger menu",
                "usage": {"input_tokens": 500, "output_tokens": 50},
            },
            operation="nav_tree_extraction",
            stage="navigation",
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            image_b64=b64,
            image_media_type="image/png",
            brand="acne.com",
        )

        target_dir = tmp_path / "navigation" / "nav_tree_extraction"
        json_files = list(target_dir.glob("acne_com_*.json"))
        png_files = list(target_dir.glob("acne_com_*.png"))
        assert len(json_files) == 1
        assert len(png_files) == 1
        assert png_files[0].read_bytes() == png_bytes

        fixture = json.loads(json_files[0].read_text())
        image_ref = fixture["input"]["image_ref"]
        assert image_ref is not None
        assert image_ref["path"] == png_files[0].name
        assert image_ref["media_type"] == "image/png"
        assert len(image_ref["sha256"]) == 64

    def test_index_jsonl_is_appended(self, tmp_path: Path):
        rec = FixtureRecorder(base_dir=tmp_path)
        for i in range(3):
            rec.record_call(
                method="call",
                prompt=f"prompt-{i}",
                output={
                    "success": True,
                    "data": {"i": i},
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
                operation="op",
                stage="urls",
                model="m",
                max_tokens=100,
                brand="b.com",
            )
        index_path = tmp_path / "index.jsonl"
        assert index_path.exists()
        lines = index_path.read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            entry = json.loads(line)
            assert set(entry.keys()) >= {
                "fixture_id",
                "timestamp",
                "stage",
                "operation",
                "brand",
                "method",
                "model",
                "path",
            }

    def test_non_serializable_output_is_stringified_not_raised(self, tmp_path: Path):
        """Recorder must not crash on Pydantic models / exceptions / etc."""

        class NotJson:
            def __repr__(self):
                return "<NotJson>"

        rec = FixtureRecorder(base_dir=tmp_path)
        rec.record_call(
            method="call",
            prompt="p",
            output={
                "success": True,
                "data": {"ok": 1},
                "weird_field": NotJson(),
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            operation="op",
            stage="urls",
            model="m",
            max_tokens=100,
            brand="b.com",
        )
        files = list(tmp_path.rglob("b_com_*.json"))
        assert len(files) == 1
        fixture = json.loads(files[0].read_text())
        assert fixture["output"]["weird_field"] == "<NotJson>"
        assert fixture["output"]["data"] == {"ok": 1}

    def test_brand_env_var_fallback(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LLM_RECORD_BRAND", "env.com")
        rec = FixtureRecorder(base_dir=tmp_path)
        rec.record_call(
            method="call",
            prompt="p",
            output={
                "success": True,
                "data": {},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            operation="op",
            stage="urls",
            model="m",
            max_tokens=100,
        )
        files = list(tmp_path.rglob("env_com_*.json"))
        assert len(files) == 1

    def test_slug_handles_weird_brand_names(self, tmp_path: Path):
        rec = FixtureRecorder(base_dir=tmp_path)
        rec.record_call(
            method="call",
            prompt="p",
            output={
                "success": True,
                "data": {},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            operation="op",
            stage="urls",
            model="m",
            max_tokens=100,
            brand="Acne Studios / Official",
        )
        files = list(tmp_path.rglob("*.json"))
        assert len(files) == 1
        name = files[0].name
        assert "/" not in name
        assert " " not in name

    def test_recorder_swallows_internal_errors(self, tmp_path: Path):
        """If the base_dir is a file (not a dir), recording must fail safely."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        rec = FixtureRecorder(base_dir=blocker)

        result = rec.record_call(
            method="call",
            prompt="p",
            output={
                "success": True,
                "data": {},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            operation="op",
            stage="urls",
            model="m",
            max_tokens=100,
            brand="b.com",
        )
        assert result is None
