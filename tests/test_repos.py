"""Tests for git repo detection (single + multi sub-repo enumeration)."""

import os
import subprocess
from pathlib import Path

import pytest

from methodproof import repos


def _git_init(path: Path, remote: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


def test_detect_repo_returns_origin(tmp_path: Path) -> None:
    _git_init(tmp_path, "https://github.com/acme/foo")
    assert repos.detect_repo(str(tmp_path)) == "https://github.com/acme/foo"


def test_detect_repo_returns_none_for_non_repo(tmp_path: Path) -> None:
    assert repos.detect_repo(str(tmp_path)) is None


def test_enumerate_sub_repos_finds_nested(tmp_path: Path) -> None:
    _git_init(tmp_path, "https://github.com/me/outer")
    _git_init(tmp_path / "pkg-a", "https://github.com/me/pkg-a")
    _git_init(tmp_path / "pkg-b", "https://github.com/me/pkg-b")

    found = repos.enumerate_sub_repos(str(tmp_path), max_depth=2)
    by_rel = {r["rel_path"]: r["remote_url"] for r in found}
    assert by_rel[""] == "https://github.com/me/outer"
    assert by_rel["pkg-a"] == "https://github.com/me/pkg-a"
    assert by_rel["pkg-b"] == "https://github.com/me/pkg-b"


def test_enumerate_sub_repos_respects_max_depth(tmp_path: Path) -> None:
    _git_init(tmp_path, "https://github.com/me/outer")
    _git_init(tmp_path / "a" / "b", "https://github.com/me/deep")

    found_shallow = repos.enumerate_sub_repos(str(tmp_path), max_depth=1)
    assert all(r["rel_path"] in ("", "a") or r["rel_path"] != "a/b" for r in found_shallow)
    rels_shallow = {r["rel_path"] for r in found_shallow}
    assert "a/b" not in rels_shallow

    found_deep = repos.enumerate_sub_repos(str(tmp_path), max_depth=2)
    rels_deep = {r["rel_path"] for r in found_deep}
    assert "a/b" in rels_deep


def test_enumerate_sub_repos_dedupes_by_remote_url(tmp_path: Path) -> None:
    _git_init(tmp_path, "https://github.com/me/outer")
    # Simulate a directory that shares a remote (unusual but we guard against it)
    _git_init(tmp_path / "clone", "https://github.com/me/outer")

    found = repos.enumerate_sub_repos(str(tmp_path), max_depth=2)
    urls = [r["remote_url"] for r in found]
    assert urls.count("https://github.com/me/outer") == 1


def test_enumerate_sub_repos_skips_non_repo_dirs(tmp_path: Path) -> None:
    _git_init(tmp_path, "https://github.com/me/outer")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "not-a-repo").mkdir()
    _git_init(tmp_path / "real", "https://github.com/me/real")

    found = repos.enumerate_sub_repos(str(tmp_path), max_depth=2)
    rels = {r["rel_path"] for r in found}
    assert "node_modules" not in rels
    assert "not-a-repo" not in rels
    assert "real" in rels
