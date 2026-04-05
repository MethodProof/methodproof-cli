# Changelog

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
