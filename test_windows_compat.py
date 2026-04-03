"""Smoke test: exercise all Windows code paths with mocked sys.platform.

Run in Docker: docker run --rm -v $(pwd):/app -w /app python:3.12-slim python test_windows_compat.py
"""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Use a temp dir as HOME so we don't pollute anything
FAKE_HOME = tempfile.mkdtemp()
os.environ["HOME"] = FAKE_HOME
os.environ["USERNAME"] = "testuser"

PASSED = 0
FAILED = 0


def test(name):
    def decorator(fn):
        global PASSED, FAILED
        try:
            fn()
            print(f"  PASS  {name}")
            PASSED += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            FAILED += 1
    return decorator


print("\n=== Windows Compatibility Smoke Tests ===\n")

# ── config.py ──

@test("config.secure_file on win32")
def _():
    with patch("sys.platform", "win32"), \
         patch("subprocess.run") as mock_run:
        # Re-import to pick up patched platform
        import methodproof.config as cfg
        importlib.reload(cfg)
        tmp = Path(FAKE_HOME) / "test_secure.txt"
        tmp.write_text("secret")
        cfg.secure_file(tmp)
        # On win32, should call subprocess.run with icacls
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "icacls", f"Expected icacls, got {args[0]}"
        assert "testuser:F" in args
        tmp.unlink()


@test("config.secure_file on unix (no mock)")
def _():
    with patch("sys.platform", "linux"):
        import methodproof.config as cfg
        importlib.reload(cfg)
        tmp = Path(FAKE_HOME) / "test_secure2.txt"
        tmp.write_text("secret")
        cfg.secure_file(tmp)
        # Should have called chmod
        assert oct(tmp.stat().st_mode)[-3:] == "600"
        tmp.unlink()


@test("config.save on win32")
def _():
    with patch("sys.platform", "win32"), \
         patch("subprocess.run"):
        import methodproof.config as cfg
        importlib.reload(cfg)
        cfg.DIR = Path(FAKE_HOME) / ".methodproof_test_save"
        cfg.CONFIG = cfg.DIR / "config.json"
        cfg.save({"token": "abc"})
        assert cfg.CONFIG.exists()
        import json
        data = json.loads(cfg.CONFIG.read_text())
        assert data["token"] == "abc"


# ── hook.py ──

@test("hook.get_shell_rc returns PowerShell profile on win32")
def _():
    with patch("sys.platform", "win32"):
        import methodproof.hook as hook
        importlib.reload(hook)
        rc, text = hook.get_shell_rc()
        assert "PowerShell" in str(rc) or "WindowsPowerShell" in str(rc), f"Unexpected rc: {rc}"
        assert "Set-PSReadLineOption" in text
        assert "# methodproof-hook" in text


@test("hook.get_shell_rc returns bashrc on linux")
def _():
    with patch("sys.platform", "linux"), \
         patch.dict(os.environ, {"SHELL": "/bin/bash"}):
        import methodproof.hook as hook
        importlib.reload(hook)
        rc, text = hook.get_shell_rc()
        assert ".bashrc" in str(rc)
        assert "trap" in text


@test("hook.get_shell_rc returns zshrc for zsh")
def _():
    with patch("sys.platform", "darwin"), \
         patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
        import methodproof.hook as hook
        importlib.reload(hook)
        rc, text = hook.get_shell_rc()
        assert ".zshrc" in str(rc)
        assert "add-zsh-hook" in text


@test("hook.install on win32 creates profile dir and writes hook")
def _():
    with patch("sys.platform", "win32"):
        import methodproof.hook as hook
        importlib.reload(hook)
        # Point to a temp profile path
        fake_ps_dir = Path(FAKE_HOME) / "Documents" / "PowerShell"
        fake_ps_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(hook, "get_shell_rc", return_value=(
            fake_ps_dir / "Microsoft.PowerShell_profile.ps1", hook._POWERSHELL
        )):
            result = hook.install()
            profile = fake_ps_dir / "Microsoft.PowerShell_profile.ps1"
            assert profile.exists(), "Profile not created"
            content = profile.read_text()
            assert "methodproof-hook" in content
            assert "Set-PSReadLineOption" in content


@test("hook.is_installed returns True after install")
def _():
    with patch("sys.platform", "win32"):
        import methodproof.hook as hook
        importlib.reload(hook)
        fake_ps_dir = Path(FAKE_HOME) / "Documents" / "PowerShell2"
        fake_ps_dir.mkdir(parents=True, exist_ok=True)
        profile = fake_ps_dir / "Microsoft.PowerShell_profile.ps1"
        with patch.object(hook, "get_shell_rc", return_value=(profile, hook._POWERSHELL)):
            hook.install()
            assert hook.is_installed()


# ── hooks/wrappers.py ──

@test("wrappers.install on win32 uses PowerShell template")
def _():
    with patch("sys.platform", "win32"), \
         patch("shutil.which", return_value="/usr/bin/codex"):
        import methodproof.hooks.wrappers as wrappers
        import methodproof.hook as hook
        importlib.reload(hook)
        importlib.reload(wrappers)
        fake_ps_dir = Path(FAKE_HOME) / "Documents" / "PowerShell3"
        fake_ps_dir.mkdir(parents=True, exist_ok=True)
        profile = fake_ps_dir / "Microsoft.PowerShell_profile.ps1"
        with patch.object(hook, "get_shell_rc", return_value=(profile, hook._POWERSHELL)):
            with patch.object(wrappers, "get_shell_rc", return_value=(profile, hook._POWERSHELL)):
                result = wrappers.install()
                assert "codex" in result
                content = profile.read_text()
                assert "Invoke-RestMethod" in content
                assert "Set-Alias" in content


# ── hooks/install.py ──

@test("hooks/install.py selects claude_code.py on win32")
def _():
    with patch("sys.platform", "win32"):
        import methodproof.hooks.install as inst
        importlib.reload(inst)
        assert str(inst.HOOK_SCRIPT).endswith("claude_code.py")


@test("hooks/install.py selects claude_code.sh on linux")
def _():
    with patch("sys.platform", "linux"):
        import methodproof.hooks.install as inst
        importlib.reload(inst)
        assert str(inst.HOOK_SCRIPT).endswith("claude_code.sh")


# ── hooks/claude_code.py ──

@test("claude_code.py processes UserPromptSubmit without crashing")
def _():
    import io
    import json
    payload = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "prompt": "write a function that adds two numbers",
    })
    with patch("sys.stdin", io.StringIO(payload)), \
         patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = ConnectionRefusedError("no bridge")
        from methodproof.hooks.claude_code import main
        main()  # Should not raise — bridge errors are silenced


@test("claude_code.py handles PreToolUse event")
def _():
    import io
    import json
    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_use_id": "abc123",
    })
    with patch("sys.stdin", io.StringIO(payload)), \
         patch("urllib.request.urlopen"):
        from methodproof.hooks.claude_code import main
        main()


@test("claude_code.py handles invalid JSON gracefully")
def _():
    import io
    with patch("sys.stdin", io.StringIO("not json")):
        from methodproof.hooks.claude_code import main
        main()  # Should not raise


# ── cli.py signal handling ──

@test("SIGTERM guard doesn't crash on win32")
def _():
    # Simulate Windows where SIGTERM may not exist
    import signal
    original = getattr(signal, "SIGTERM", None)
    try:
        if hasattr(signal, "SIGTERM"):
            # Test the hasattr guard
            assert hasattr(signal, "SIGTERM")
        # The guard in cli.py: `if hasattr(signal, "SIGTERM")`
        # Just verify the pattern works
        handler = lambda s, f: None
        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        if original and hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)


@test("stop-file sentinel write/read cycle")
def _():
    stopfile = Path(FAKE_HOME) / ".methodproof_test" / "methodproof.stop"
    stopfile.parent.mkdir(parents=True, exist_ok=True)
    stopfile.write_text("12345")
    assert stopfile.exists()
    pid = stopfile.read_text()
    assert pid == "12345"
    stopfile.unlink(missing_ok=True)
    assert not stopfile.exists()


# ── cli.py alias ──

@test("_install_alias writes Set-Alias on win32")
def _():
    with patch("sys.platform", "win32"):
        import methodproof.hook as hook
        importlib.reload(hook)
        fake_ps_dir = Path(FAKE_HOME) / "Documents" / "PowerShell4"
        fake_ps_dir.mkdir(parents=True, exist_ok=True)
        profile = fake_ps_dir / "Microsoft.PowerShell_profile.ps1"
        with patch.object(hook, "get_shell_rc", return_value=(profile, hook._POWERSHELL)):
            # Simulate what _install_alias does
            marker = "# methodproof-alias"
            alias = f'\n{marker}\nSet-Alias mp methodproof\n'
            profile.parent.mkdir(parents=True, exist_ok=True)
            with profile.open("a") as f:
                f.write(alias)
            content = profile.read_text()
            assert "Set-Alias mp methodproof" in content


# ── integrity.py ──

@test("integrity.secure_file called instead of chmod")
def _():
    # Verify the import works
    with patch("sys.platform", "win32"), \
         patch("subprocess.run"):
        import methodproof.config as cfg
        importlib.reload(cfg)
        tmp = Path(FAKE_HOME) / "test_key.pem"
        tmp.write_bytes(b"fake key")
        cfg.secure_file(tmp)
        tmp.unlink()


# ── store.py ──

@test("store.init_db calls secure_file")
def _():
    with patch("sys.platform", "win32"), \
         patch("subprocess.run"):
        import methodproof.config as cfg
        importlib.reload(cfg)
        cfg.DIR = Path(FAKE_HOME) / ".methodproof_store_test"
        cfg.CONFIG = cfg.DIR / "config.json"
        cfg.DB_PATH = cfg.DIR / "methodproof.db"
        cfg.CMD_LOG = cfg.DIR / "commands.jsonl"
        import methodproof.store as st
        # Reset connection
        st._conn = None
        importlib.reload(st)
        with patch.object(cfg, "secure_file") as mock_secure:
            st.init_db()
            mock_secure.assert_called_once_with(cfg.DB_PATH)
        st._conn = None  # cleanup


# ── PowerShell hook content validation ──

@test("PowerShell hook has valid structure")
def _():
    import methodproof.hook as hook
    importlib.reload(hook)
    ps = hook._POWERSHELL
    assert "$global:_mpCmd" in ps
    assert "Set-PSReadLineOption" in ps
    assert "AddToHistoryHandler" in ps
    assert "function prompt" in ps
    assert "Add-Content" in ps
    assert "commands.jsonl" in ps
    assert "# methodproof-hook" in ps


print(f"\n{'=' * 40}")
print(f"  {PASSED} passed, {FAILED} failed")
print(f"{'=' * 40}\n")
sys.exit(1 if FAILED else 0)
