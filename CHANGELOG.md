# Changelog

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
