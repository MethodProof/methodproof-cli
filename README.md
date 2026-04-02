# MethodProof

See how you code — capture and visualize your engineering process.

```bash
pip install methodproof
methodproof init     # install hooks, acknowledge data capture
methodproof start    # begin recording
# ... code ...
methodproof stop     # stop recording, build process graph
methodproof view     # explore session graph in browser
```

No account required. Fully offline. Your data stays on your machine unless you explicitly `push`.

## Commands

| Command | Description |
|---------|-------------|
| `init` | Install hooks, create data directory. Interactive consent selector on first run |
| `start [--dir .] [--repo URL] [--tags t1,t2] [--public]` | Start recording a session |
| `stop` | Stop recording, build process graph |
| `view [session_id] [--port 9876]` | View session graph in browser (D3 visualization) |
| `log` | List local sessions with sync status, visibility, tags |
| `login [--api-url URL]` | Connect to MethodProof platform (email + password) |
| `push [session_id]` | Upload session to platform |
| `tag <session_id> <tags>` | Add comma-separated tags to a session |
| `publish [session_id]` | Set visibility to public and push |
| `delete <session_id> [-f]` | Delete a session and all its data (with confirmation) |
| `consent` | Review or change capture categories at any time |
| `mcp-serve` | Run MCP server (used by Claude Code integration) |

## Consent & Capture Categories

On first `init`, MethodProof shows an interactive consent selector. You choose exactly which categories of data to capture — nothing is recorded without your explicit opt-in.

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
  [x] 7. ai_prompts           Text you send to AI tools (Claude Code, OpenClaw, codex, etc.)
  [x] 8. ai_responses         Text AI tools respond with, including tool calls
  [x] 9. browser              Page visits, tab switches, searches, copy events (via extension)

  Toggle: enter number | a = all on | n = all off | done = confirm
```

Categories are enforced at every level:
- **Agent level** — disabled agents don't start (no CPU/memory overhead)
- **Event level** — events from disabled categories are silently dropped
- **Field level** — `command_output` and `git_diffs` strip specific fields from events that are otherwise captured

Change your choices anytime with `methodproof consent`.

### What Each Category Captures

| Category | Events | Details |
|----------|--------|---------|
| `terminal_commands` | `terminal_cmd` | Command text, exit code, duration. Sensitive commands (passwords, tokens, API keys) are auto-filtered |
| `command_output` | (field in `terminal_cmd`) | First 500 chars of stdout. Redacted if it contains sensitive patterns |
| `test_results` | `test_run` | Framework name, pass/fail counts, duration |
| `file_changes` | `file_create`, `file_edit`, `file_delete` | File paths, sizes, language, line counts |
| `git_diffs` | (field in `file_edit`) | Diff content (max 2000 chars). Redacted for secret files (`.env`, `.pem`, credentials) |
| `git_commits` | `git_commit` | Short hash, commit message, changed file list |
| `ai_prompts` | `llm_prompt`, `agent_prompt` | Model name, prompt text, token count, temperature |
| `ai_responses` | `llm_completion`, `agent_completion`, tool events | Response text, token count, latency, tool calls |
| `browser` | `browser_visit`, `browser_search`, `browser_tab_switch`, `browser_copy`, `browser_ai_chat` | Metadata only — no page content, no search query text, no copied text |

All data is stored locally in `~/.methodproof/methodproof.db` (SQLite, `chmod 600`).

## Deleting Data

```bash
# Delete a session and all related data
methodproof delete <session_id>

# Skip confirmation prompt
methodproof delete <session_id> --force
```

## E2E Encryption

For company-managed encryption where the platform cannot read your data:

```bash
pip install methodproof[e2e]
```

Set your company's encryption key in `~/.methodproof/config.json`:

```json
{
  "e2e_key": "<64-char-hex-key>"
}
```

When set, all sensitive metadata (prompts, completions, commands, output, diffs) is encrypted with AES-256-GCM before storage and before any platform sync. The platform stores ciphertext it cannot decrypt.

## Connecting to Platform

```bash
methodproof login                    # authenticate
methodproof push                     # upload latest session
methodproof push abc123              # upload specific session
methodproof publish                  # set public + push
methodproof tag abc123 python,react  # add tags
```

For self-hosted instances:

```bash
methodproof login --api-url https://mp.company.com/api
```

## Integrations

`methodproof init` automatically installs hooks for detected tools:

- **Shell** — bash/zsh preexec/precmd hooks for command capture
- **Claude Code** — hooks for prompt/tool/session events
- **OpenClaw** — hook + skill for agent-level telemetry
- **AI CLI wrappers** — codex, gemini, aider command wrappers
- **MCP server** — registered with Claude Code for session/graph queries

## Configuration

Data directory: `~/.methodproof/`

| File | Purpose |
|------|---------|
| `config.json` | API URL, auth token, email, E2E key (`chmod 600`) |
| `methodproof.db` | SQLite database with sessions, events, graph (`chmod 600`) |
| `commands.jsonl` | Shell command log (consumed by terminal monitor) |
