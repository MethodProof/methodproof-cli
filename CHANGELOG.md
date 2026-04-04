# Changelog

## 2026-04-04

### Changed
- **README rebrand** — OG dark banner, hero process graph illustration, brand-colored badges (gold/purple/green). Value prop and features up front. Consent, integrity, and encryption details in collapsible `<details>` blocks. Added `review` and `update` to command reference.

## 2026-04-02

### Added
- **`--live` flag on `methodproof start`** — streams events to the platform in
  real-time over WebSocket. Requires login (`methodproof login`). Creates the
  remote session automatically and connects to `WS /sessions/{id}/stream`.
- **`methodproof/live.py`** — WebSocket client module using `websocket-client`.
  Performs JWT + consent handshake, then drains a thread-safe send queue in a
  background thread. Events are sent to both local SQLite and the live WebSocket.
- **`live` optional dependency** — `pip install methodproof[live]` adds
  `websocket-client>=1.7`.
- Free-tier users with full-spectrum consent (all 10 categories enabled) get
  30-day rolling live stream access. Pro/Team users get unlimited.
