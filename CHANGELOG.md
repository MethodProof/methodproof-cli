# Changelog

## [0.7.23] — 2026-04-12

### Fixed
- **`mp` alias works immediately after `init`** — `_install_alias` now creates a real symlink (`mp → methodproof`) in the same bin directory instead of writing an rc alias. No shell restart or eval needed. Falls back to rc alias if symlinking fails (e.g. read-only bin dir).

## [0.7.22] — 2026-04-11

### Added
- **Username in session output** — `mp start` banner shows `Account: @username` (falls back to email). `mp stop` summary shows the same. Username fetched from `/auth/me` on login and stored in config profile.

### Fixed
- **`eval "$(methodproof shell-hook)"` missing `mp` alias** — `shell-hook` now emits both the command-logging hooks and `alias mp="methodproof"`, so eval fully activates the CLI without a shell restart.

## [0.7.20] — 2026-04-11

### Fixed
- **TUI init layout** — toggle rows now use `height: auto` so long capture descriptions don't clip; `width: 1fr` on `.row-label` overrides the 24-char truncation from base CSS; Switch widgets widened from 4→6 for correct rendering; Full Spectrum status no longer cut off at 1 line
- **TUI consent layout** — Switch widgets widened from 4→6 (same fix as init)
- **TUI status markup** — `_token_expiry()` was returning Rich markup strings into `Text.append()`, which treats input as plain text; tags now rendered literally (e.g. `[#d93326]expires soon[/#d93326]`). Fixed to return `(text, style)` tuple and apply styles at call site
- **Session complete timeout** — `mp push` was using 15s for the final `/complete` call, which times out on large sessions while the server drains the ingest queue and materializes stats. Raised to 90s. Timeout is now a configurable parameter on internal request helpers

## [0.7.6] — 2026-04-08

### Added
- **Metadata compression** — event metadata stored as zlib-compressed BLOBs in SQLite (~80% storage reduction for journal-mode sessions). Existing uncompressed rows are silently migrated on next startup.
- **Gzip transfer encoding** — `mp push` sends gzip-compressed request bodies to the platform. Reduces upload bandwidth ~70% for large batches.

## [0.7.1] — 2026-04-07

### Fixed
- **7 GB database bloat** — `artifacts` table lacked a UNIQUE constraint on `path`, causing `_ensure_artifact` to insert a duplicate row per `file_edit`. The `_link_action_artifacts` JOIN then produced a cartesian explosion (39.9M rows from 16K events). Added UNIQUE constraint + migration that deduplicates existing data on upgrade.
- **Stale PID after reboot** — `_is_daemon_alive()` only checked `os.kill(pid, 0)`, which succeeds if the OS reused the PID for an unrelated process. Now verifies the process name contains "methodproof" via `ps`. Prevents killing random processes and unblocks `mp stop`/`mp start` after a system restart.
- **SQLite hang on locked database** — `sqlite3.connect()` had no timeout, so a crashed daemon holding a WAL lock caused `mp stop` to hang forever. Added `timeout=10`.

### Added
- **Research consent sync** — `mp init`, `mp consent`, `mp login`, and `mp push` now sync research opt-in state between CLI and platform. Local changes are flagged with `_pending_research_sync` and pushed on next authenticated call; canonical state is always pulled from the platform.

## [0.7.0] — 2026-04-07

### Fixed
- **Runaway event logging** — watcher ignored only 7 patterns, tracking 35K+ files including `.venv/` (20K), `dist/build/` (23K). Expanded to 30+ ignore patterns covering Python, JS/TS, Rust, Go, Java, Ruby, PHP, .NET, Swift, and build artifacts. **138K → 1,442 files (99% reduction)**
- **Claude Code hook errors** — hook script pointed to deleted pyenv site-packages path; added pidfile guard (`exit 0` when no session active) to prevent bridge connection failures

### Added
- **Configurable local AI ports** — `mp init` now asks about local LLM servers (Ollama, LM Studio, vLLM, etc.) and adds user-specified ports to the proxy allowlist. Previously only 3 hardcoded ports (11434, 18789, 1234) were captured; custom ports were invisible to the proxy decoder.
- `mp start --streaming` — blocking foreground mode, streams every captured event to stdout in real-time with human-readable formatting
- `mp start --verbose` / `-v` — structured debug logging at each step (config, auth, session, anchor, daemon spawn); daemon log includes agent init and buffer/flush stats
- Step-by-step progress output on default `mp start` (`→ Loading config`, `→ Checking hooks`, etc.) so failures are immediately locatable

## [0.5.1] — 2026-04-06

### Fixed
- macOS daemon segfault: replaced `os.fork()` with `subprocess.Popen()` — CoreFoundation crash after fork killed all capture agents, producing 0 events
- Hook type mismatches: `task_created`→`task_start`, `task_completed`→`task_end`, added required `tool` field to all hook metadata
- Unmapped hook events dropped instead of sent as invalid `claude_code_event` type (rejected entire batch)
- Daemon output logged to `~/.methodproof/daemon.log` instead of `/dev/null`
- ~20 silent `except Exception: pass` blocks replaced with structured logging across bridge, hooks, live streaming, sync, keychain, MCP, and proxy

### Changed
- Daemon health check on startup — immediate error if daemon exits
- Extension status check shows actual error on failure

## [0.3.4] — 2026-04-05

### Added
- `mp log` shows session status: recording, stopped, pushed, empty, abandoned
- `mp log` prints sync reminder when unsynced sessions exist

## [0.3.3] — 2026-04-05

### Fixed
- macOS hook timestamp: `date +%s.%3N` produced invalid JSON (literal `.3N`), silently dropping all tool_call, tool_result, agent_launch, and agent_complete events
- Stale session recovery: `mp start` now detects dead daemons and cleans up instead of blocking
- Bridge events now route through `base.emit()` for consent gating, hash chain integrity, and live streaming

### Changed
- `mp view` replaced with terminal-based session audit (no HTTP server)
- Recording threads start after fork (fixes silent 0-event sessions on macOS)
- Hook errors logged to `~/.methodproof/hook_errors.log` for inspection
- Consent-blocked events logged at debug level

### Added
- Watch Scope section in README documenting directory scope and exclusion patterns
- `store.reset_connection()` for fork-safe SQLite WAL handling

## [0.3.2] — 2026-04-04

### Changed
- `websocket-client` is now a default dependency (no longer requires `pip install methodproof[live]`)
- `mp start --live` prints a clickable dashboard URL instead of the API host
- `live.start()` returns the dashboard URL from the platform handshake

## [0.3.1] — 2026-04-04

### Added
- `mp extension pair` — pair browser extension to active session
- `mp extension status` — check extension connection
- `mp extension install` — open Chrome Web Store listing
- Bridge auto-discovery: extension auto-connects when CLI session starts
- Bridge `/pair/auto` endpoint for extension auto-pairing
- Bridge `/pair/register` + `/pair/ack` for manual pairing flow
- `mp start` now runs in the background (daemon mode on Unix)
- Extension status check on session start (connected/not detected)
- `SO_REUSEADDR` on bridge socket for clean restarts

### Changed
- Bridge accepts API credentials for auto-discovery passthrough
- `_shutdown` handler wrapped in try/except for robust daemon cleanup

## [0.3.0] — 2026-04-03

### Added
- Prompt structural analysis: 35 metadata dimensions extracted from AI prompts
- Environment profiling: structural scan of AI dev environment (instruction files, tool configs)
- `environment_analysis` consent category (default on, structural metadata only)
- Outcome metrics: correlation between prompt patterns and session results
- Consent review prompt when new capture categories exist after update

### Changed
- README rebrand: OG dark banner, hero process graph, brand-colored badges

### Fixed
- Unused import, silent failures, operator precedence, magic numbers (code review)

## [0.2.0] — 2026-03-30

### Added
- Browser login via device auth flow (`mp login` opens browser)
- Three-section interactive consent (capture, research, redaction)
- `mp uninstall` — remove all hooks, data, and config
- Color-coded command reference (`mp help`)
- Auto-refresh expired API tokens
- `mp update` — self-update from PyPI
- AI Agent Graph branding for prompt/response events
- Code capture consent category (Pro only, encrypted, default off)
- Windows compatibility (stop sentinel, icacls permissions)
- `--live` flag streams events to platform in real-time over WebSocket
- `live` optional dependency (`pip install methodproof[live]`)
- Free-tier full-spectrum consent unlocks 30-day rolling live stream

## [0.1.1] — 2026-03-28

### Fixed
- Added pytest dev dependency

## [0.1.0] — 2026-03-27

### Added
- Initial release
- `mp init/start/stop/view/log/push/publish/review/consent/tag/delete`
- File watcher, terminal monitor, music agent
- Local bridge for browser extension events
- Hash-chained events + Ed25519 attestation
- Full Spectrum messaging (all 10 categories)
- `mp mcp-serve` — MCP server for Claude Code
