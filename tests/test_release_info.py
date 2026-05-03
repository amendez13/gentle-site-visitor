"""Tests for release metadata helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.module_loader import import_source_module

release_info_module = import_source_module("release_info")


def test_get_release_info_prefers_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RELEASE_TAG", "v1.2.3")
    monkeypatch.setenv("RELEASE_COMMIT", "abc123456789")

    info = release_info_module.get_release_info()

    assert info == {
        "tag": "v1.2.3",
        "commit": "abc123456789",
        "short_commit": "abc1234",
        "source": "env",
    }


def test_get_release_info_falls_back_to_git(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    monkeypatch.delenv("RELEASE_COMMIT", raising=False)

    def fake_run(args, cwd, capture_output, text, timeout, check):  # type: ignore[no-untyped-def]
        command = tuple(args[1:])
        outputs = {
            ("rev-parse", "HEAD"): "abc123456789\n",
            ("rev-parse", "--short", "HEAD"): "abc1234\n",
            ("describe", "--tags", "--exact-match"): "v1.2.3\n",
        }
        stdout = outputs.get(command, "")
        return SimpleNamespace(returncode=0 if stdout else 1, stdout=stdout)

    monkeypatch.setattr(release_info_module.subprocess, "run", fake_run)

    info = release_info_module.get_release_info()

    assert info == {
        "tag": "v1.2.3",
        "commit": "abc123456789",
        "short_commit": "abc1234",
        "source": "git",
    }


def test_get_release_info_falls_back_to_version_file(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    monkeypatch.delenv("RELEASE_COMMIT", raising=False)
    monkeypatch.setattr(release_info_module, "_git_output", lambda *args: None)

    version_file = tmp_path / "VERSION"
    version_file.write_text("v9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(release_info_module, "_VERSION_FILE", version_file)

    info = release_info_module.get_release_info()

    assert info == {
        "tag": "v9.9.9",
        "commit": None,
        "short_commit": None,
        "source": "version_file",
    }
