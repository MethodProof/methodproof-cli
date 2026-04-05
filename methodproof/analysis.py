"""Prompt structural analysis — extracts metadata signals, never stores content."""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_TOKEN_PER_WORD = 1.3
_BUG_REPORT_WORD_LIMIT = 200


def _warn(event: str, **kw: object) -> None:
    """Minimal warning to stderr — analysis.py is stdlib-only, no StructuredLogger."""
    sys.stderr.write(json.dumps({"level": "warning", "event": event, **kw}, default=str) + "\n")

# ---------------------------------------------------------------------------
# Intent classification (first-match cascade, ordered by specificity)
# ---------------------------------------------------------------------------
_RE_SELECTION = re.compile(
    r"^(option\s+[A-Z0-9]|[0-9]|yes|no|y|n|agreed|sounds good|go ahead|lgtm)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_RE_CORRECTION = re.compile(
    r"^(no[,.\s]|nope|not that|instead[,.\s]|actually[,.\s]|wrong|don'?t\s|stop\s|"
    r"that'?s not|I meant|I said|undo|revert)",
    re.IGNORECASE,
)
_RE_BUG_REPORT = re.compile(
    r"(Traceback \(most recent|Error:|Exception:|stack trace|FAILED|panic:|"
    r"Segmentation fault|SIGSEGV|core dumped|undefined is not|Cannot read propert|"
    r"TypeError:|ValueError:|KeyError:|AttributeError:|ImportError:|ModuleNotFoundError:|"
    r"SyntaxError:|RuntimeError:|ConnectionError:|TimeoutError:|FileNotFoundError:|"
    r"PermissionError:|OSError:|IndexError:|ZeroDivisionError:|"
    r"NullPointerException|ClassNotFoundException|NoSuchMethodError|"
    r"segfault|SIGABRT|SIGKILL|exit code [1-9])",
    re.IGNORECASE | re.MULTILINE,
)
_RE_STRATEGIC_Q = re.compile(
    r"\b(how can we|how should we|what'?s the best way to|best approach|"
    r"what strategy|how do we approach|what'?s the right way)\b",
    re.IGNORECASE,
)
_RE_DESIGN_Q = re.compile(
    r"\b(how would|what if we|could we|would it make sense|would it be possible|"
    r"what would happen if|should we consider|what are the trade-?offs)\b",
    re.IGNORECASE,
)
_RE_STATUS_Q = re.compile(
    r"\b(are we|did (this|we|it)|is (this|it) done|have we|do we have|"
    r"is there (a|any)|does (this|it) (work|exist|have))\b",
    re.IGNORECASE,
)
_RE_FACTUAL_Q = re.compile(
    r"\b(what is|what are|what does|where is|where are|when did|when does|"
    r"which (one|file|function)|who (wrote|owns|maintains)|how many|how much)\b",
    re.IGNORECASE,
)
_RE_VERIFICATION = re.compile(
    r"\b(check (if|whether|that)|verify|is this (correct|right|ok|safe)|"
    r"in line with|does this (match|align|comply|satisfy|meet)|compatible|"
    r"make sure|confirm|validate|looks? (right|good|correct))\b",
    re.IGNORECASE,
)
_RE_COLLABORATIVE = re.compile(
    r"\b(let'?s|we could|how about (we)?|shall we|want to|we should|"
    r"I think we|together|collaborate|pair on)\b",
    re.IGNORECASE,
)
_RE_DECISION = re.compile(
    r"(option\s+[A-Z0-9]|\bthe\s+(first|second|third|last|former|latter)\b|"
    r"\bchoice\s+[A-Z0-9]\b|\bapproach\s+[A-Z0-9]\b|I'?d go with|"
    r"I prefer|let'?s go with)",
    re.IGNORECASE,
)
_RE_IMPERATIVE = re.compile(
    r"^\s*(fix|add|build|create|change|remove|update|implement|refactor|rename|"
    r"move|delete|write|explain|show|run|deploy|test|make|set|configure|install|"
    r"migrate|merge|revert|clean|lint|format|extract|inline|wrap|unwrap|split|"
    r"combine|replace|convert|transform|generate|parse|serialize|deserialize|"
    r"fetch|send|post|push|pull|sync|start|stop|restart|kill|debug|trace|"
    r"profile|benchmark|optimize|simplify|document|log|print|dump|inspect|"
    r"list|find|search|grep|look|read|open|close|connect|disconnect|enable|"
    r"disable|toggle|switch|swap|hook|unhook|register|unregister|mount|unmount)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Cognitive level
# ---------------------------------------------------------------------------
_RE_COG_INFO = re.compile(
    r"\b(what|where|when|which|who|does|is|are|was|were|has|have|had)\b",
    re.IGNORECASE,
)
_RE_COG_ANALYSIS = re.compile(
    r"\b(how|why|decompose|compare|what causes|analyze|investigate|debug|"
    r"diagnose|trace|profile|understand|figure out|root cause|difference between)\b",
    re.IGNORECASE,
)
_RE_COG_SYNTHESIS = re.compile(
    r"\b(design|build|think|plan|create|architect|draft|propose|devise|"
    r"come up with|brainstorm|imagine|envision|sketch|outline|prototype)\b",
    re.IGNORECASE,
)
_RE_COG_EVAL = re.compile(
    r"\b(check|verify|review|is this correct|in line with|evaluate|assess|"
    r"audit|validate|critique|judge|rate|score|compare against|benchmark)\b",
    re.IGNORECASE,
)
_RE_COG_EXEC = re.compile(
    r"\b(fix|change|add|remove|rename|implement|update|refactor|deploy|"
    r"install|configure|migrate|write|delete|replace|move|merge|revert)\b",
    re.IGNORECASE,
)
_RE_COG_DECISION = re.compile(
    r"(option\s+[A-Z0-9]|\byes\b|\bno\b|\bgo with\b|\bI prefer\b|\blet'?s do\b)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Structural features
# ---------------------------------------------------------------------------
_RE_CODE_BLOCK = re.compile(r"^```(\w*)", re.MULTILINE)
_RE_INLINE_CODE = re.compile(r"(?<!`)`(?!`)([^`\n]+)`(?!`)")
_RE_FILE_PATH = re.compile(
    r"(?:^|[\s\"'(,])("
    r"[a-zA-Z0-9_./~-]+/"                   # at least one directory separator
    r"[a-zA-Z0-9_./-]+"                      # rest of path
    r"(?:\.[a-zA-Z]{1,10})?"                 # optional extension
    r")(?:[\s\"'),;:\]]|$)",
    re.MULTILINE,
)
_RE_LINE_NUMBER = re.compile(
    r"(?::(\d+)\b|\blines?\s+(\d+)\b|\bL(\d+)\b|\bline\s*#?\s*(\d+)\b)",
    re.IGNORECASE,
)
_RE_ERROR_TRACE = re.compile(
    r"(Traceback|Error:|Exception:|^\s+at\s+\S|panic:|FAILED|"
    r"^\s+File \"[^\"]+\", line \d+|"
    r"^\s+\^\^\^\^\^)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_URL = re.compile(r"https?://[^\s)\]>\"']+")
_RE_DIFF = re.compile(r"^[+-]{1,3}\s|^@@\s", re.MULTILINE)
_RE_QUOTED = re.compile(r"""(?<!\w)(['"])(?:(?!\1).){1,200}\1(?!\w)""")
_RE_NUMERIC = re.compile(r"(?<!\w)\d+\.?\d*(?!\w)")
_RE_SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")

# ---------------------------------------------------------------------------
# Specificity
# ---------------------------------------------------------------------------
_RE_SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_RE_CAMEL_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+\b")
_RE_PASCAL_CASE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_TECH_TERMS = frozenset({
    "python", "javascript", "typescript", "react", "vue", "angular", "svelte",
    "neo4j", "redis", "postgres", "postgresql", "mysql", "sqlite", "mongodb",
    "docker", "kubernetes", "k8s", "nginx", "caddy", "aws", "gcp", "azure",
    "node", "deno", "bun", "rust", "go", "golang", "java", "kotlin", "swift",
    "django", "flask", "fastapi", "express", "nextjs", "nuxt", "vite",
    "graphql", "rest", "grpc", "websocket", "kafka", "rabbitmq",
    "terraform", "tofu", "ansible", "github", "gitlab", "npm", "pip", "uv",
    "pytest", "jest", "vitest", "cypress", "playwright",
    "pydantic", "sqlalchemy", "alembic", "prisma",
    "tailwind", "css", "html", "sass", "scss",
    "linux", "macos", "windows", "ubuntu", "debian",
    "bash", "zsh", "powershell", "curl", "wget",
    "json", "yaml", "toml", "xml", "csv", "protobuf",
    "jwt", "oauth", "oidc", "cors", "tls", "ssl",
    "s3", "ec2", "ecs", "rds", "lambda", "cloudfront",
    "ci", "cd", "git", "svn", "mercurial",
    "http", "https", "tcp", "udp", "dns",
    "cpu", "gpu", "ram", "ssd", "io",
    "api", "sdk", "cli", "gui", "tui", "mcp",
    "d3", "three.js", "webgl", "canvas", "svg",
})

# ---------------------------------------------------------------------------
# Context dependency
# ---------------------------------------------------------------------------
_RE_PRONOUN = re.compile(r"\b(it|this|that|these|those)\b", re.IGNORECASE)
_RE_PRIOR_TURN = re.compile(
    r"\b(above|previous|earlier|what about|as I said|like I mentioned|"
    r"as we discussed|from before|you (just|already)|the last|the same)\b",
    re.IGNORECASE,
)
_RE_CONTINUATION = re.compile(
    r"^(also|and|but|then|now|ok|okay|right|so|actually|wait|"
    r"oh|hmm|well|plus|additionally|furthermore|moreover|however)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Prompt structure
# ---------------------------------------------------------------------------
_RE_SEQUENCING = re.compile(
    r"\b(first|then|next|after that|finally|step\s+\d|second|third|lastly|"
    r"to start|before that|once that'?s done|afterwards)\b",
    re.IGNORECASE,
)
_RE_CONSTRAINT = re.compile(
    r"\b(don'?t|without|only|keep|must not|avoid|never|"
    r"do not|shouldn'?t|won'?t|can'?t|leave .+ as.is|"
    r"except|but not|other than|unless)\b",
    re.IGNORECASE,
)
_RE_NEG_CONSTRAINT = re.compile(
    r"\b(don'?t|never|must not|avoid|do not|shouldn'?t|stop|"
    r"no more|no longer|cease|quit|refrain)\b",
    re.IGNORECASE,
)
_RE_ACCEPTANCE = re.compile(
    r"\b(it should|should (be|have|return|work|pass|fail|throw|render|display)|"
    r"expected|make sure|ensure|must (be|have|return)|"
    r"verify that|assert|the result should|the output should)\b",
    re.IGNORECASE,
)
_RE_SCOPE = re.compile(
    r"\b(across|in all|every file|the entire|throughout|globally|"
    r"everywhere|all (files|modules|tests|routes|components)|"
    r"the whole|codebase-wide|repo-wide|project-wide)\b",
    re.IGNORECASE,
)
_RE_PARENTHETICAL = re.compile(r"\([^)]{2,}\)")

# ---------------------------------------------------------------------------
# Environment scan: content category classifiers (line-level)
# ---------------------------------------------------------------------------
_RE_CAT_SCHEMA = re.compile(
    r"(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|"
    r"\(:?\w+\)\s*[<-]|"                          # Neo4j node patterns
    r"\binterface\s+\w+\s*\{|\btype\s+\w+\s*=|"
    r"\bclass\s+\w+|"
    r"\benum\s+\w+|"
    r"\bschema\b|\.schema\b|"
    r"REFERENCES\s+\w+|PRIMARY\s+KEY|FOREIGN\s+KEY|"
    r"NOT\s+NULL|UNIQUE|DEFAULT\s|INDEX\s+)",
    re.IGNORECASE,
)
_RE_CAT_ARCH = re.compile(
    r"([─│┌┐└┘├┤┬┴┼╔╗╚╝║═►▼▲◄→←↑↓]|"
    r"\bservice\b|\blayer\b|\bflow\b|-->|->|==>|"
    r"\bpipeline\b|\bqueue\b|\bstream\b|\bbus\b|"
    r"\bmicroservice\b|\bgateway\b|\bproxy\b|\bload.?balancer\b)",
    re.IGNORECASE,
)
_RE_CAT_BEHAVIORAL = re.compile(
    r"\b(must\b|MUST\b|never\b|NEVER\b|always\b|ALWAYS\b|"
    r"do not\b|DO NOT\b|shall not|SHALL NOT|IMPORTANT:|"
    r"required|REQUIRED|forbidden|FORBIDDEN|"
    r"you (must|should|shall)|we (must|should|shall))\b",
    re.IGNORECASE,
)
_RE_CAT_STYLE = re.compile(
    r"\b(prefer\b|avoid\b|use\s+\w+\s+over|instead of|"
    r"naming\b|convention\b|format\b|indent\b|"
    r"snake.case|camelCase|PascalCase|kebab.case|"
    r"lint\b|eslint|prettier|black|ruff|mypy|"
    r"style\s+guide|coding\s+standard)\b",
    re.IGNORECASE,
)
_RE_CAT_COMMAND = re.compile(
    r"(^\s*\$\s+\w|^\s*`[^`]+`\s*$|"
    r"^\s*(just|make|npm|yarn|pip|uv|cargo|go|docker|kubectl)\s+\w|"
    r"^\s*```(bash|sh|shell|zsh|console|terminal))",
    re.IGNORECASE | re.MULTILINE,
)
_RE_CAT_API = re.compile(
    r"(\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+/|"
    r"/api/|/v[0-9]+/|"
    r"\b[1-5]\d\d\b.*\b(OK|Created|Not Found|Unauthorized|Forbidden|Error)\b|"
    r"endpoint|request|response|payload|header|query\s+param|"
    r"Content-Type|Authorization|Bearer)",
    re.IGNORECASE,
)

_CATEGORY_PATTERNS = [
    ("schema_definitions", _RE_CAT_SCHEMA),
    ("architecture_docs", _RE_CAT_ARCH),
    ("behavioral_rules", _RE_CAT_BEHAVIORAL),
    ("style_conventions", _RE_CAT_STYLE),
    ("command_reference", _RE_CAT_COMMAND),
    ("api_contracts", _RE_CAT_API),
]

# Markdown structural patterns for environment scan
_RE_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)
_RE_MD_TABLE_SEP = re.compile(r"^\s*\|[\s:-]+\|", re.MULTILINE)
_RE_MD_LIST_ITEM = re.compile(r"^\s*[-*+]\s|^\s*\d+\.\s", re.MULTILINE)


# ===================================================================
# Public API
# ===================================================================


def analyze_prompt(text: str) -> dict[str, Any]:
    """Extract structural metadata from a prompt. No content stored. <50ms."""
    if not text or not text.strip():
        return {"sa_intent": "empty", "sa_cognitive_level": "none", "sa_word_count": 0}

    stripped = text.strip()
    words = stripped.split()
    word_count = len(words)

    # --- Size ---
    line_count = text.count("\n") + 1
    char_count = len(text)
    sentence_count = max(1, len(_RE_SENTENCE_SPLIT.split(stripped)))
    token_estimate = int(word_count * _TOKEN_PER_WORD)

    # --- Structural features ---
    code_blocks = _RE_CODE_BLOCK.findall(text)
    code_block_count = len(code_blocks)
    code_languages = [lang for lang in code_blocks if lang]
    has_code_blocks = code_block_count > 0

    inline_codes = _RE_INLINE_CODE.findall(text)
    inline_code_count = len(inline_codes)
    has_inline_code = inline_code_count > 0

    file_paths = _RE_FILE_PATH.findall(text)
    file_path_count = len(file_paths)
    has_file_paths = file_path_count > 0

    has_line_numbers = bool(_RE_LINE_NUMBER.search(text))

    error_matches = _RE_ERROR_TRACE.findall(text)
    has_error_trace = len(error_matches) > 0
    error_trace_lines = len(error_matches)

    urls = _RE_URL.findall(text)
    url_count = len(urls)
    has_url = url_count > 0

    has_diff = bool(_RE_DIFF.search(text))
    has_quoted_string = bool(_RE_QUOTED.search(text))
    has_numeric_values = bool(_RE_NUMERIC.search(stripped))

    # --- Specificity ---
    named_files = file_path_count
    named_functions = len(_RE_SNAKE_CASE.findall(text)) + len(_RE_CAMEL_CASE.findall(text))
    named_classes = len(_RE_PASCAL_CASE.findall(text))
    words_lower = {w.lower().rstrip(".,;:!?") for w in words}
    named_technologies = sum(1 for w in words_lower if w in _TECH_TERMS)
    referents = named_files + named_functions + named_classes + named_technologies
    specificity_score = round(min(1.0, referents / max(word_count, 1)), 3)

    # --- Context dependency ---
    pronoun_count = len(_RE_PRONOUN.findall(text))
    references_prior = bool(_RE_PRIOR_TURN.search(text))
    is_follow_up = bool(_RE_CONTINUATION.match(stripped))

    if word_count < 5:
        context_dependency = "total"
    elif is_follow_up or pronoun_count > 2 or references_prior:
        context_dependency = "high"
    elif pronoun_count > 0:
        context_dependency = "medium"
    else:
        context_dependency = "low"

    # --- Intent classification (first match wins) ---
    intent = _classify_intent(stripped, word_count, has_error_trace)

    # --- Cognitive level (highest signal) ---
    cognitive_level = _classify_cognitive(stripped, intent)

    # --- Collaboration mode ---
    if intent == "correction":
        collaboration_mode = "correcting"
    elif intent in ("decision", "selection"):
        collaboration_mode = "selecting"
    elif _RE_VERIFICATION.search(text):
        collaboration_mode = "reviewing"
    elif _RE_COLLABORATIVE.search(text):
        collaboration_mode = "thinking_together"
    else:
        collaboration_mode = "delegating"

    # --- Prompt structure ---
    is_selection = bool(_RE_SELECTION.match(stripped))
    has_sequencing = bool(_RE_SEQUENCING.search(text))
    has_constraints = bool(_RE_CONSTRAINT.search(text))
    has_negative_constraints = bool(_RE_NEG_CONSTRAINT.search(text))
    has_acceptance_criteria = bool(_RE_ACCEPTANCE.search(text))
    has_scope_definition = bool(_RE_SCOPE.search(text))
    has_parenthetical = bool(_RE_PARENTHETICAL.search(text))

    # Compound: multiple imperative verbs on separate lines or semicolons
    imperative_lines = sum(
        1 for line in text.splitlines()
        if _RE_IMPERATIVE.match(line.strip())
    )
    is_compound = imperative_lines >= 2 or (";" in text and _RE_IMPERATIVE.search(text))

    return {
        "sa_intent": intent,
        "sa_cognitive_level": cognitive_level,
        "sa_token_estimate": token_estimate,
        "sa_word_count": word_count,
        "sa_line_count": line_count,
        "sa_char_count": char_count,
        "sa_sentence_count": sentence_count,
        "sa_has_code_blocks": has_code_blocks,
        "sa_code_block_count": code_block_count,
        "sa_code_languages": code_languages,
        "sa_has_inline_code": has_inline_code,
        "sa_inline_code_count": inline_code_count,
        "sa_has_file_paths": has_file_paths,
        "sa_file_path_count": file_path_count,
        "sa_has_line_numbers": has_line_numbers,
        "sa_has_error_trace": has_error_trace,
        "sa_error_trace_lines": error_trace_lines,
        "sa_has_url": has_url,
        "sa_url_count": url_count,
        "sa_has_diff": has_diff,
        "sa_has_quoted_string": has_quoted_string,
        "sa_has_numeric_values": has_numeric_values,
        "sa_named_files": named_files,
        "sa_named_functions": named_functions,
        "sa_named_classes": named_classes,
        "sa_named_technologies": named_technologies,
        "sa_specificity_score": specificity_score,
        "sa_context_dependency": context_dependency,
        "sa_pronoun_count": pronoun_count,
        "sa_references_prior_turn": references_prior,
        "sa_is_follow_up": is_follow_up,
        "sa_collaboration_mode": collaboration_mode,
        "sa_is_compound": bool(is_compound),
        "sa_has_sequencing": has_sequencing,
        "sa_has_constraints": has_constraints,
        "sa_has_negative_constraints": has_negative_constraints,
        "sa_has_acceptance_criteria": has_acceptance_criteria,
        "sa_has_scope_definition": has_scope_definition,
        "sa_has_parenthetical": has_parenthetical,
        "sa_is_selection": is_selection,
    }


def compose_summary(meta: dict[str, Any]) -> str:
    """Compose a readable prompt summary from structural analysis fields.

    Replaces dumb 200-char truncation with a meaningful, searchable summary.
    Zero API calls — purely local composition from already-extracted sa_* fields.

    Examples:
      "[instruction/synthesis] refactor app/auth/middleware.py — dependency injection"
      "[bug_report/execution] fix TypeError in utils.py:parse_config — Python, JSON"
      "[design_question/analysis] caching strategy — Redis, PostgreSQL, 3 constraints"
      "[correction] not that approach — references prior turn"
    """
    intent = meta.get("sa_intent", "unknown")
    cognitive = meta.get("sa_cognitive_level", "")
    files = meta.get("sa_named_files", [])
    functions = meta.get("sa_named_functions", [])
    classes = meta.get("sa_named_classes", [])
    technologies = meta.get("sa_named_technologies", [])
    languages = meta.get("sa_code_languages", [])
    collab = meta.get("sa_collaboration_mode", "")

    # Header: [intent/cognitive]
    header = f"[{intent}"
    if cognitive and cognitive != "none":
        header += f"/{cognitive}"
    header += "]"

    # Entities: files, functions, classes, technologies
    parts: list[str] = []
    if files:
        parts.extend(files[:3])
    if functions:
        parts.extend(functions[:2])
    if classes:
        parts.extend(classes[:2])
    if technologies:
        parts.extend(technologies[:4])
    elif languages:
        parts.extend(languages[:2])

    # Qualifiers
    qualifiers: list[str] = []
    if meta.get("sa_has_error_trace"):
        qualifiers.append(f"{meta.get('sa_error_trace_lines', 0)} error lines")
    if meta.get("sa_has_constraints"):
        qualifiers.append("constrained")
    if meta.get("sa_has_acceptance_criteria"):
        qualifiers.append("with criteria")
    if meta.get("sa_is_compound"):
        qualifiers.append("multi-part")
    if meta.get("sa_references_prior_turn"):
        qualifiers.append("references prior turn")
    if meta.get("sa_code_block_count", 0) > 0:
        qualifiers.append(f"{meta['sa_code_block_count']} code blocks")

    # Compose
    summary = header
    if parts:
        summary += " " + ", ".join(dict.fromkeys(parts))  # dedupe preserving order
    if qualifiers:
        summary += " — " + ", ".join(qualifiers[:3])

    return summary


def scan_environment(watch_dir: str) -> dict[str, Any]:
    """Scan filesystem for AI instruction files and config. No content stored."""
    home = Path.home()
    claude_dir = home / ".claude"
    watch = Path(watch_dir).resolve()
    encoded = str(watch).replace("/", "-").lstrip("-")

    candidates = [
        ("claude_global", claude_dir / "CLAUDE.md"),
        ("claude_project", watch / "CLAUDE.md"),
        ("claude_user_project", claude_dir / "projects" / encoded / "CLAUDE.md"),
        ("cursorrules", watch / ".cursorrules"),
        ("copilot_instructions", watch / ".github" / "copilot-instructions.md"),
    ]

    instruction_files = []
    for pattern, path in candidates:
        if not path.exists():
            continue
        try:
            content = path.read_text(errors="replace")
        except OSError as exc:
            _warn("analysis.instruction_file.read_failed", path_pattern=pattern, error=str(exc))
            continue
        instruction_files.append(_analyze_instruction_file(pattern, content))

    tool_ecosystem = _analyze_tool_ecosystem(claude_dir)

    fingerprints = "".join(f["fingerprint"] for f in instruction_files)
    composite_fp = hashlib.sha256(fingerprints.encode()).hexdigest() if fingerprints else ""

    return {
        "total_instruction_files": len(instruction_files),
        "total_instruction_tokens": sum(f["token_estimate"] for f in instruction_files),
        "instruction_files": instruction_files,
        "tool_ecosystem": tool_ecosystem,
        "fingerprint": composite_fp,
    }


def compute_outcomes(session_id: str) -> dict[str, Any]:
    """Compute prompt effectiveness metrics from session events. Runs post-graph-build."""
    from methodproof.store import _db

    db = _db()
    prompt_types = ("user_prompt", "llm_prompt", "agent_prompt")
    completion_types = ("llm_completion", "agent_completion")

    total_prompts = db.execute(
        "SELECT count(*) FROM events WHERE session_id = ? AND type IN (?, ?, ?)",
        (session_id, *prompt_types),
    ).fetchone()[0]

    if total_prompts == 0:
        return {"total_prompts": 0}

    total_completions = db.execute(
        "SELECT count(*) FROM events WHERE session_id = ? AND type IN (?, ?)",
        (session_id, *completion_types),
    ).fetchone()[0]

    # First-shot apply rate: completions that INFORMED a file_edit
    applied = db.execute(
        "SELECT count(DISTINCT cl.source_id) FROM causal_links cl "
        "JOIN events e ON e.id = cl.source_id "
        "WHERE e.session_id = ? AND cl.type = 'INFORMED'",
        (session_id,),
    ).fetchone()[0]
    first_shot_rate = round(applied / max(total_completions, 1), 3)

    # Follow-up sequences: consecutive prompt events
    events = db.execute(
        "SELECT type, metadata FROM events WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()

    sequences, current_run = 0, 0
    run_lengths: list[int] = []
    for e in events:
        if e["type"] in prompt_types:
            current_run += 1
        else:
            if current_run > 1:
                sequences += 1
                run_lengths.append(current_run)
            current_run = 0
    if current_run > 1:
        sequences += 1
        run_lengths.append(current_run)

    avg_follow_up = round(sum(run_lengths) / max(len(run_lengths), 1), 1)

    # Intent/selection counts from sa_ metadata
    corrections, decisions, selections = 0, 0, 0
    cognitive_levels: list[str] = []
    specificities: list[float] = []
    dep_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "total": 0}

    for e in events:
        if e["type"] not in prompt_types:
            continue
        try:
            meta = json.loads(e["metadata"])
        except (json.JSONDecodeError, TypeError) as exc:
            _warn("analysis.metadata_parse_failed", event_id=e["id"] if hasattr(e, "__getitem__") else "?", error=str(exc))
            continue
        intent = meta.get("sa_intent")
        if intent == "correction":
            corrections += 1
        if intent == "decision":
            decisions += 1
        if meta.get("sa_is_selection"):
            selections += 1
        cog = meta.get("sa_cognitive_level")
        if cog:
            cognitive_levels.append(cog)
        spec = meta.get("sa_specificity_score")
        if spec is not None:
            specificities.append(spec)
        dep = meta.get("sa_context_dependency")
        if dep in dep_dist:
            dep_dist[dep] += 1

    # Phase transitions: cognitive level changes between consecutive prompts
    transitions = sum(
        1 for i in range(1, len(cognitive_levels))
        if cognitive_levels[i] != cognitive_levels[i - 1]
    )

    avg_spec = round(sum(specificities) / max(len(specificities), 1), 3)

    return {
        "total_prompts": total_prompts,
        "total_completions": total_completions,
        "first_shot_apply_rate": first_shot_rate,
        "follow_up_sequences": sequences,
        "avg_follow_up_length": avg_follow_up,
        "corrections_detected": corrections,
        "decisions_detected": decisions,
        "selections_detected": selections,
        "phase_transitions": transitions,
        "avg_specificity": avg_spec,
        "context_dependency_dist": dep_dist,
    }


# ===================================================================
# Internal helpers
# ===================================================================


def _classify_intent(text: str, word_count: int, has_error: bool) -> str:
    """First-match cascade for intent classification."""
    if _RE_SELECTION.match(text):
        return "selection"
    if _RE_CORRECTION.search(text):
        return "correction"
    if has_error and word_count < _BUG_REPORT_WORD_LIMIT:
        return "bug_report"
    is_question = "?" in text
    if is_question:
        if _RE_STRATEGIC_Q.search(text):
            return "strategic_question"
        if _RE_DESIGN_Q.search(text):
            return "design_question"
        if _RE_STATUS_Q.search(text):
            return "status_question"
        if _RE_FACTUAL_Q.search(text):
            return "factual_question"
        if _RE_VERIFICATION.search(text):
            return "verification"
    elif _RE_VERIFICATION.search(text):
        return "verification"
    if _RE_COLLABORATIVE.search(text):
        return "collaborative_design"
    if _RE_DECISION.search(text):
        return "decision"
    if _RE_IMPERATIVE.search(text):
        return "instruction"
    if is_question:
        return "factual_question"
    return "statement"


def _classify_cognitive(text: str, intent: str) -> str:
    """Score each cognitive level, return highest."""
    if intent in ("selection", "decision"):
        return "decision"

    scores = {
        "evaluation": len(_RE_COG_EVAL.findall(text)),
        "synthesis": len(_RE_COG_SYNTHESIS.findall(text)),
        "analysis": len(_RE_COG_ANALYSIS.findall(text)),
        "execution": len(_RE_COG_EXEC.findall(text)),
        "information": len(_RE_COG_INFO.findall(text)),
    }
    # Tie-break: higher levels win (order above is the priority)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "information"


def _analyze_instruction_file(pattern: str, content: str) -> dict[str, Any]:
    """Extract structural metadata from an instruction file."""
    lines = content.splitlines()
    line_count = len(lines)
    word_count = len(content.split())
    token_estimate = int(word_count * _TOKEN_PER_WORD)

    headings = _RE_MD_HEADING.findall(content)
    section_count = len(headings)
    max_depth = max((len(h[0]) for h in headings), default=0)

    code_blocks = _RE_CODE_BLOCK.findall(content)
    code_block_count = len(code_blocks)
    code_block_languages = list({lang for lang in code_blocks if lang})

    table_count = len(_RE_MD_TABLE_SEP.findall(content))
    list_item_count = len(_RE_MD_LIST_ITEM.findall(content))

    fingerprint = hashlib.sha256(content.encode()).hexdigest()

    # Content category distribution (line-level classification)
    category_counts: dict[str, int] = {name: 0 for name, _ in _CATEGORY_PATTERNS}
    category_counts["domain_knowledge"] = 0
    classified = 0

    for line in lines:
        if not line.strip():
            continue
        matched = False
        for name, pat in _CATEGORY_PATTERNS:
            if pat.search(line):
                category_counts[name] += 1
                matched = True
                break
        if not matched:
            category_counts["domain_knowledge"] += 1
        classified += 1

    total = max(classified, 1)
    category_dist = {k: round(v / total, 3) for k, v in category_counts.items()}

    return {
        "path_pattern": pattern,
        "token_estimate": token_estimate,
        "line_count": line_count,
        "section_count": section_count,
        "max_heading_depth": max_depth,
        "code_block_count": code_block_count,
        "code_block_languages": code_block_languages,
        "table_count": table_count,
        "list_item_count": list_item_count,
        "fingerprint": fingerprint,
        "category_distribution": category_dist,
    }


def _analyze_tool_ecosystem(claude_dir: Path) -> dict[str, Any]:
    """Extract tool/hook/MCP metadata from Claude Code settings files."""
    result: dict[str, Any] = {
        "hook_event_count": 0,
        "total_hook_count": 0,
        "plugin_count": 0,
        "plugin_names": [],
        "mcp_server_count": 0,
        "mcp_server_names": [],
        "mcp_json_server_count": 0,
    }

    # settings.json — hooks and plugins
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _warn("analysis.settings_parse_failed", path="settings.json", error=str(exc))
            settings = {}

        hooks = settings.get("hooks", {})
        result["hook_event_count"] = len(hooks)
        result["total_hook_count"] = sum(
            len(h) for groups in hooks.values() for g in (groups if isinstance(groups, list) else []) for h in g.get("hooks", [])
        )

        plugins = settings.get("enabledPlugins", {})
        enabled = [k for k, v in plugins.items() if v]
        result["plugin_count"] = len(enabled)
        result["plugin_names"] = [p.split("@")[0] for p in enabled]

    # settings.local.json — MCP servers
    local_path = claude_dir / "settings.local.json"
    if local_path.exists():
        try:
            local = json.loads(local_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _warn("analysis.settings_parse_failed", path="settings.local.json", error=str(exc))
            local = {}

        mcp = local.get("mcpServers", {})
        result["mcp_server_count"] = len(mcp)
        result["mcp_server_names"] = list(mcp.keys())

        mcp_json = local.get("enabledMcpjsonServers", [])
        result["mcp_json_server_count"] = len(mcp_json)
        result["mcp_server_names"] = list(set(result["mcp_server_names"] + list(mcp_json)))

    return result
