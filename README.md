<p align="center">
  <img src="https://cdn.methodproof.com/og/og-primary-dark.png" alt="MethodProof — Engineering Process Intelligence" width="720" />
</p>

<p align="center">
  <a href="https://pypi.org/project/methodproof/"><img src="https://img.shields.io/pypi/v/methodproof?color=%23c9a84c&style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/methodproof/"><img src="https://img.shields.io/pypi/pyversions/methodproof?color=%23803794&style=flat-square" alt="Python"></a>
  <a href="https://github.com/MethodProof/methodproof-cli/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-%232d7a42?style=flat-square" alt="License"></a>
</p>

# MethodProof

**Your engineering process, visualized as a knowledge graph.**

MethodProof captures how you work — terminal commands, file edits, git commits, AI interactions — and renders it as an interactive process graph you can explore, share, and prove.

No account required. Fully offline. Your data stays on your machine unless you explicitly push it.

<p align="center">
  <img src="https://cdn.methodproof.com/illustrations/hero-light.png" alt="Process graph — every action connected as a timeline" width="720" />
</p>

## Install

```bash
pip install methodproof
```

## Quick Start

```bash
methodproof init      # choose what to capture, install hooks
methodproof start     # begin recording
# ... code normally ...
methodproof stop      # stop recording, build process graph
methodproof view      # explore your session in the browser
```

`methodproof view` opens a D3-powered interactive graph: every action is a node, every relationship is an edge. You see exactly how your session unfolded — which commands led to which edits, when you consulted AI, where you hit dead ends and recovered.

## Features

- **Process graph** — D3 interactive visualization of your entire session as a knowledge graph
- **Granular consent** — 9 capture categories, each independently toggled. Nothing records without your opt-in
- **Local-first** — SQLite database at `~/.methodproof/`, `chmod 600`. No network calls unless you choose
- **Live streaming** — `methodproof start --live` streams events to the platform in real-time over WebSocket
- **Integrity verification** — hash-chained events + Ed25519 attestation prove sessions haven't been tampered with
- **E2E encryption** — optional company-held AES-256-GCM encryption the platform cannot decrypt
- **Auto-detection** — hooks for shell, Claude Code, OpenClaw, codex, gemini, aider installed automatically
- **Platform sync** — `methodproof push` uploads sessions. `methodproof publish` makes them public and shareable

## Commands

| Command | What it does |
|---------|-------------|
| `init` | Interactive consent selector, install hooks, create data directory |
| `start [--dir .] [--tags t1,t2] [--public] [--live]` | Start recording |
| `stop` | Stop recording, build process graph |
| `view [session_id]` | Open session graph in browser |
| `log` | List sessions with sync status, visibility, tags |
| `login` | Authenticate with the platform |
| `push [session_id]` | Upload session |
| `publish [session_id]` | Set public + push |
| `tag <session_id> <tags>` | Add tags |
| `delete <session_id> [-f]` | Delete session and all its data |
| `consent` | Change capture categories |
| `review` | Inspect session data before pushing |
| `update` | Check for and install CLI updates |

## Privacy & Consent

<details>
<summary>How consent works</summary>

On first `init`, you choose exactly which categories to capture:

```
MethodProof Consent — choose what to capture

All data stays local in ~/.methodproof/. Nothing leaves your
machine unless you explicitly run `methodproof push`.

  [x] 1. terminal_commands    Commands you run and their exit codes
  [x] 2. command_output       First 500 chars of command output (secrets auto-filtered)
  [x] 3. test_results         Pass/fail counts from pytest, jest, go test, cargo test
  [x] 4. file_changes         File create, edit, and delete events with paths and sizes
  [x] 5. git_diffs            Diff content of file changes (secrets auto-redacted)
  [x] 6. git_commits          Commit hashes, messages, and changed file lists
  [x] 7. ai_prompts           Text you send to AI tools
  [x] 8. ai_responses         Text AI tools respond with
  [x] 9. browser              Page visits, tab switches, searches, copy events (via extension)

  Toggle: enter number | a = all on | n = all off | done = confirm
```

Categories are enforced at three levels:
- **Agent level** — disabled agents don't start
- **Event level** — events from disabled categories are dropped
- **Field level** — specific fields stripped from events that are otherwise captured

Change anytime with `methodproof consent`. Inspect data before pushing with `methodproof review`.

</details>

<details>
<summary>Capture categories reference</summary>

| Category | Events | Details |
|----------|--------|---------|
| `terminal_commands` | `terminal_cmd` | Command text, exit code, duration. Sensitive commands auto-filtered |
| `command_output` | field in `terminal_cmd` | First 500 chars of stdout. Redacted for sensitive patterns |
| `test_results` | `test_run` | Framework name, pass/fail counts, duration |
| `file_changes` | `file_create`, `file_edit`, `file_delete` | File paths, sizes, language, line counts |
| `git_diffs` | field in `file_edit` | Diff content (max 2000 chars). Redacted for secret files |
| `git_commits` | `git_commit` | Short hash, commit message, changed file list |
| `ai_prompts` | `llm_prompt`, `agent_prompt` | Model name, prompt text, token count |
| `ai_responses` | `llm_completion`, `agent_completion` | Response text, token count, latency, tool calls |
| `browser` | browser events | Metadata only — no page content, no search text, no copied text |

</details>

## Integrity & Encryption

<details>
<summary>Integrity verification</summary>

Three layers ensure session data hasn't been tampered with:

**Hash-chained events** — every event includes a SHA-256 hash linking to the previous event. Any modification breaks the chain, detectable via `GET /sessions/{id}/chain/verify`.

**Ed25519 attestation** — on `methodproof push`, the CLI signs a session summary with your private key. Install with `pip install methodproof[signing]`. Key generated during `methodproof init`, stored in `~/.methodproof/config.json`.

**Binary hash self-reporting** — the CLI reports its own binary hash on push. The platform compares against known release hashes to detect modified builds.

</details>

<details>
<summary>E2E encryption</summary>

For company-managed encryption where the platform cannot read your data:

```bash
pip install methodproof[e2e]
```

Set your company's key in `~/.methodproof/config.json`:

```json
{ "e2e_key": "<64-char-hex-key>" }
```

All sensitive metadata (prompts, completions, commands, output, diffs) is encrypted with AES-256-GCM before storage and before any platform sync.

</details>

## Integrations

`methodproof init` auto-detects and installs hooks for:

- **Shell** — bash/zsh preexec/precmd hooks
- **Claude Code** — prompt, tool, and session event hooks
- **OpenClaw** — hook + skill for agent telemetry
- **AI CLIs** — codex, gemini, aider command wrappers
- **MCP server** — registered with Claude Code for session/graph queries

## Data Directory

`~/.methodproof/`

| File | Purpose |
|------|---------|
| `config.json` | API URL, auth token, E2E key (chmod 600) |
| `methodproof.db` | Sessions, events, graph (chmod 600) |
| `commands.jsonl` | Shell command log |

## License

[Apache 2.0](LICENSE)
