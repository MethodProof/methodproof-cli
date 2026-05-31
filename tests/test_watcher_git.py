"""Tests for git dir resolution — normal clones vs worktrees."""

import subprocess
from pathlib import Path

from methodproof.agents import watcher


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    # CI runners have no global git identity; commits need a local one.
    subprocess.run(["git", "config", "user.email", "test@methodproof.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=path, check=True)


def test_resolve_git_dirs_normal_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    git_dir, common_dir = watcher._resolve_git_dirs(str(tmp_path))
    assert git_dir == common_dir
    assert (git_dir / "HEAD").is_file()


def test_resolve_git_dirs_worktree(tmp_path: Path) -> None:
    main = tmp_path / "main"
    _git_init(main)
    wt = tmp_path / "wt-feature"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feature"],
                   cwd=main, check=True)

    git_dir, common_dir = watcher._resolve_git_dirs(str(wt))
    # Worktree HEAD is per-worktree; shared refs live in the common dir.
    assert git_dir != common_dir
    assert watcher._read_branch(git_dir / "HEAD") == "feature"
    assert (common_dir / "refs" / "heads" / "feature").is_file()


def test_resolve_git_dirs_non_repo(tmp_path: Path) -> None:
    assert watcher._resolve_git_dirs(str(tmp_path)) is None
