"""Tests for methodproof.analysis — prompt structural analysis, env scan, outcomes."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from methodproof.analysis import analyze_prompt, compute_outcomes, scan_environment


# ===================================================================
# analyze_prompt — intent classification
# ===================================================================


class TestIntent:
    def test_empty(self):
        r = analyze_prompt("")
        assert r["sa_intent"] == "empty"
        assert r["sa_word_count"] == 0

    def test_whitespace(self):
        r = analyze_prompt("   \n\n  ")
        assert r["sa_intent"] == "empty"

    def test_selection_option_b(self):
        r = analyze_prompt("Option B")
        assert r["sa_intent"] == "selection"
        assert r["sa_is_selection"] is True
        assert r["sa_context_dependency"] == "total"

    def test_selection_yes(self):
        r = analyze_prompt("yes")
        assert r["sa_intent"] == "selection"

    def test_selection_number(self):
        r = analyze_prompt("2")
        assert r["sa_intent"] == "selection"

    def test_correction_no(self):
        r = analyze_prompt("no, not that approach — use the other one")
        assert r["sa_intent"] == "correction"
        assert r["sa_collaboration_mode"] == "correcting"

    def test_correction_dont(self):
        r = analyze_prompt("don't add error handling — just the bare function")
        assert r["sa_intent"] == "correction"

    def test_correction_actually(self):
        r = analyze_prompt("actually, use Redis instead of PostgreSQL for this")
        assert r["sa_intent"] == "correction"

    def test_bug_report(self):
        r = analyze_prompt(
            "I'm getting TypeError: Cannot read properties of undefined\n"
            "  at Dashboard.render (src/Dashboard.tsx:47)\n"
            "  at Object.run (node_modules/react/index.js:123)\n"
            "why is this failing?"
        )
        assert r["sa_intent"] == "bug_report"
        assert r["sa_has_error_trace"] is True
        assert r["sa_error_trace_lines"] > 0

    def test_strategic_question(self):
        r = analyze_prompt(
            "How can we build effective analysis into the prompts captured from users?"
        )
        assert r["sa_intent"] == "strategic_question"
        assert r["sa_cognitive_level"] == "synthesis"

    def test_design_question(self):
        r = analyze_prompt(
            "How would it be possible to decompose system context into metadata?"
        )
        assert r["sa_intent"] == "design_question"

    def test_status_question(self):
        r = analyze_prompt("Are we doing any analysis on the actual prompts?")
        assert r["sa_intent"] == "status_question"

    def test_factual_question(self):
        r = analyze_prompt("What is the default port for Redis?")
        assert r["sa_intent"] == "factual_question"
        assert r["sa_cognitive_level"] == "information"

    def test_verification(self):
        r = analyze_prompt("is all of this still in line with our terms of use?")
        assert r["sa_intent"] == "verification"
        assert r["sa_collaboration_mode"] == "reviewing"

    def test_collaborative(self):
        r = analyze_prompt("Let's think deeply about all the params we would pass into this")
        assert r["sa_intent"] == "collaborative_design"
        assert r["sa_collaboration_mode"] == "thinking_together"

    def test_decision(self):
        r = analyze_prompt("I'd go with the second approach for the migration")
        assert r["sa_intent"] == "decision"
        assert r["sa_collaboration_mode"] == "selecting"

    def test_instruction(self):
        r = analyze_prompt("Fix the auth bug in the login endpoint")
        assert r["sa_intent"] == "instruction"
        assert r["sa_collaboration_mode"] == "delegating"

    def test_instruction_rename(self):
        r = analyze_prompt(
            "Rename SessionRecord to Session across the platform codebase"
        )
        assert r["sa_intent"] == "instruction"

    def test_statement_fallback(self):
        r = analyze_prompt("The migration ran successfully last night")
        assert r["sa_intent"] == "statement"


# ===================================================================
# analyze_prompt — cognitive level
# ===================================================================


class TestCognitive:
    def test_information(self):
        r = analyze_prompt("What is the default timeout?")
        assert r["sa_cognitive_level"] == "information"

    def test_analysis(self):
        r = analyze_prompt("Why is the latency so high on this endpoint?")
        assert r["sa_cognitive_level"] == "analysis"

    def test_synthesis(self):
        r = analyze_prompt("Design a caching layer for the session scores")
        assert r["sa_cognitive_level"] == "synthesis"

    def test_evaluation(self):
        r = analyze_prompt("Review this implementation and check for edge cases")
        assert r["sa_cognitive_level"] == "evaluation"

    def test_execution(self):
        r = analyze_prompt("Add a new column to the users table")
        assert r["sa_cognitive_level"] == "execution"

    def test_decision(self):
        r = analyze_prompt("Option A")
        assert r["sa_cognitive_level"] == "decision"


# ===================================================================
# analyze_prompt — structural features
# ===================================================================


class TestStructural:
    def test_code_blocks(self):
        r = analyze_prompt("Run this:\n```python\nprint('hello')\n```\nDoes it work?")
        assert r["sa_has_code_blocks"] is True
        assert r["sa_code_block_count"] >= 1
        assert "python" in r["sa_code_languages"]

    def test_inline_code(self):
        r = analyze_prompt("Change `session_id` to `sid` in `base.py`")
        assert r["sa_has_inline_code"] is True
        assert r["sa_inline_code_count"] == 3

    def test_file_paths(self):
        r = analyze_prompt("Look at src/api/routes/sessions.py and fix the timeout")
        assert r["sa_has_file_paths"] is True
        assert r["sa_file_path_count"] >= 1

    def test_line_numbers(self):
        r = analyze_prompt("The error is on line 42 of Dashboard.tsx")
        assert r["sa_has_line_numbers"] is True

    def test_line_number_colon(self):
        r = analyze_prompt("See src/main.py:142 for the issue")
        assert r["sa_has_line_numbers"] is True

    def test_urls(self):
        r = analyze_prompt("Check https://api.methodproof.com/health for status")
        assert r["sa_has_url"] is True
        assert r["sa_url_count"] == 1

    def test_diff(self):
        r = analyze_prompt("What does this change?\n+++ new line\n--- old line\n@@ -1,3 +1,4 @@")
        assert r["sa_has_diff"] is True

    def test_error_trace_python(self):
        r = analyze_prompt(
            'Traceback (most recent call last):\n'
            '  File "app.py", line 42, in main\n'
            'ValueError: invalid literal'
        )
        assert r["sa_has_error_trace"] is True

    def test_quoted_string(self):
        r = analyze_prompt('Change the label from "Submit" to "Save"')
        assert r["sa_has_quoted_string"] is True

    def test_numeric(self):
        r = analyze_prompt("Change the timeout from 60 to 120 seconds")
        assert r["sa_has_numeric_values"] is True


# ===================================================================
# analyze_prompt — specificity
# ===================================================================


class TestSpecificity:
    def test_high_specificity(self):
        r = analyze_prompt(
            "In src/api/routes/sessions.py line 142, change the RECEIVED "
            "link timeout from 60 to 120 seconds"
        )
        assert r["sa_specificity_score"] > 0.0
        assert r["sa_named_files"] >= 1
        assert r["sa_has_line_numbers"] is True

    def test_low_specificity(self):
        r = analyze_prompt("make it look better")
        assert r["sa_specificity_score"] < 0.1

    def test_technology_detection(self):
        r = analyze_prompt("Set up a FastAPI endpoint with PostgreSQL and Redis")
        assert r["sa_named_technologies"] >= 3

    def test_function_names(self):
        r = analyze_prompt("Rename analyze_prompt to extract_metadata in analysis.py")
        assert r["sa_named_functions"] >= 2

    def test_class_names(self):
        r = analyze_prompt("Change SessionRecord to Session and UserProfile to Profile")
        assert r["sa_named_classes"] >= 2


# ===================================================================
# analyze_prompt — context dependency
# ===================================================================


class TestContext:
    def test_total_dependency(self):
        r = analyze_prompt("yes")
        assert r["sa_context_dependency"] == "total"

    def test_high_dependency_follow_up(self):
        r = analyze_prompt("Also, what about the caching layer?")
        assert r["sa_is_follow_up"] is True
        assert r["sa_context_dependency"] in ("high", "total")

    def test_high_dependency_prior_ref(self):
        r = analyze_prompt("As we discussed earlier, the auth flow needs work")
        assert r["sa_references_prior_turn"] is True
        assert r["sa_context_dependency"] == "high"

    def test_low_dependency(self):
        # No pronouns, no prior-turn references, no continuation markers
        r = analyze_prompt(
            "Create a new file at src/utils/hash.py exporting a sha256 function"
        )
        assert r["sa_context_dependency"] == "low"

    def test_medium_dependency(self):
        r = analyze_prompt("Can you fix that endpoint to return a 404?")
        assert r["sa_context_dependency"] in ("medium", "high")
        assert r["sa_pronoun_count"] >= 1


# ===================================================================
# analyze_prompt — prompt structure
# ===================================================================


class TestStructure:
    def test_sequencing(self):
        r = analyze_prompt("First add the migration, then update the model, finally run tests")
        assert r["sa_has_sequencing"] is True

    def test_constraints(self):
        r = analyze_prompt("Refactor the auth module without changing the public API")
        assert r["sa_has_constraints"] is True

    def test_negative_constraints(self):
        r = analyze_prompt("Don't add error handling or logging")
        assert r["sa_has_negative_constraints"] is True

    def test_acceptance_criteria(self):
        r = analyze_prompt("Add a health check endpoint — it should return 200 with {status: ok}")
        assert r["sa_has_acceptance_criteria"] is True

    def test_scope_definition(self):
        r = analyze_prompt("Rename session_id to sid across the entire codebase")
        assert r["sa_has_scope_definition"] is True

    def test_parenthetical(self):
        r = analyze_prompt("Update the config (but keep the defaults) for production")
        assert r["sa_has_parenthetical"] is True

    def test_compound(self):
        r = analyze_prompt("Fix the auth bug\nAdd a test for it\nDeploy to staging")
        assert r["sa_is_compound"] is True


# ===================================================================
# scan_environment
# ===================================================================


class TestScanEnvironment:
    @pytest.fixture(autouse=True)
    def _isolate_home(self, tmp_path, monkeypatch):
        """Isolate from real ~/.claude by patching Path.home()."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    def test_scans_current_dir(self, tmp_path):
        watch = tmp_path / "project"
        watch.mkdir()
        claude = watch / "CLAUDE.md"
        claude.write_text("# Project\n\n## Architecture\n\nSome docs.\n\n```python\nx = 1\n```\n")
        result = scan_environment(str(watch))
        assert result["total_instruction_files"] >= 1
        files = [f for f in result["instruction_files"] if f["path_pattern"] == "claude_project"]
        assert len(files) == 1
        f = files[0]
        assert f["section_count"] == 2
        assert "python" in f["code_block_languages"]
        assert f["fingerprint"] == hashlib.sha256(claude.read_text().encode()).hexdigest()

    def test_empty_dir(self, tmp_path):
        watch = tmp_path / "empty_project"
        watch.mkdir()
        result = scan_environment(str(watch))
        assert result["total_instruction_files"] == 0
        assert result["total_instruction_tokens"] == 0
        assert result["fingerprint"] == ""

    def test_category_distribution(self, tmp_path):
        watch = tmp_path / "project"
        watch.mkdir()
        claude = watch / "CLAUDE.md"
        claude.write_text(
            "# Schema\n\n"
            "CREATE TABLE users (id INT PRIMARY KEY);\n"
            "CREATE TABLE sessions (id INT PRIMARY KEY);\n\n"
            "# Rules\n\n"
            "You must NEVER skip tests.\n"
            "You must ALWAYS use typed returns.\n"
        )
        result = scan_environment(str(watch))
        f = result["instruction_files"][0]
        dist = f["category_distribution"]
        assert dist["schema_definitions"] > 0
        assert dist["behavioral_rules"] > 0

    def test_tool_ecosystem_graceful(self, tmp_path):
        """Tool ecosystem returns zeros when no Claude Code config exists."""
        watch = tmp_path / "project"
        watch.mkdir()
        result = scan_environment(str(watch))
        eco = result["tool_ecosystem"]
        assert eco["hook_event_count"] == 0
        assert eco["plugin_count"] == 0
        assert eco["mcp_server_count"] == 0


# ===================================================================
# compute_outcomes
# ===================================================================


class TestComputeOutcomes:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        """Create an in-memory SQLite DB and patch store._db to use it."""
        import methodproof.store as store_mod

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(store_mod._SCHEMA)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS event_hashes "
            "(event_id TEXT PRIMARY KEY, hash TEXT NOT NULL)"
        )
        conn.commit()

        monkeypatch.setattr(store_mod, "_conn", conn)
        return conn

    def _insert(self, db, session_id, events):
        for e in events:
            meta = json.dumps(e.get("metadata", {}))
            db.execute(
                "INSERT INTO events (id, session_id, type, timestamp, duration_ms, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (e["id"], session_id, e["type"], e["ts"], 0, meta),
            )
        db.commit()

    def test_empty_session(self, db):
        r = compute_outcomes("empty-session")
        assert r["total_prompts"] == 0

    def test_basic_counts(self, db):
        sid = "test-session"
        self._insert(db, sid, [
            {"id": "p1", "type": "user_prompt", "ts": 1.0, "metadata": {"sa_intent": "instruction"}},
            {"id": "c1", "type": "llm_completion", "ts": 2.0, "metadata": {}},
            {"id": "p2", "type": "user_prompt", "ts": 3.0, "metadata": {"sa_intent": "correction"}},
            {"id": "c2", "type": "llm_completion", "ts": 4.0, "metadata": {}},
            {"id": "e1", "type": "file_edit", "ts": 5.0, "metadata": {}},
        ])
        # Add causal link: c2 INFORMED e1
        db.execute("INSERT INTO causal_links VALUES ('c2', 'e1', 'INFORMED', 1.0)")
        db.commit()

        r = compute_outcomes(sid)
        assert r["total_prompts"] == 2
        assert r["total_completions"] == 2
        assert r["first_shot_apply_rate"] == 0.5
        assert r["corrections_detected"] == 1

    def test_follow_up_sequences(self, db):
        sid = "followup"
        self._insert(db, sid, [
            {"id": "p1", "type": "user_prompt", "ts": 1.0, "metadata": {}},
            {"id": "p2", "type": "user_prompt", "ts": 2.0, "metadata": {}},
            {"id": "p3", "type": "user_prompt", "ts": 3.0, "metadata": {}},
            {"id": "e1", "type": "file_edit", "ts": 4.0, "metadata": {}},
            {"id": "p4", "type": "user_prompt", "ts": 5.0, "metadata": {}},
        ])
        r = compute_outcomes(sid)
        assert r["follow_up_sequences"] == 1
        assert r["avg_follow_up_length"] == 3.0

    def test_phase_transitions(self, db):
        sid = "phases"
        self._insert(db, sid, [
            {"id": "p1", "type": "user_prompt", "ts": 1.0,
             "metadata": {"sa_cognitive_level": "synthesis", "sa_specificity_score": 0.1}},
            {"id": "p2", "type": "user_prompt", "ts": 2.0,
             "metadata": {"sa_cognitive_level": "information", "sa_specificity_score": 0.3}},
            {"id": "p3", "type": "user_prompt", "ts": 3.0,
             "metadata": {"sa_cognitive_level": "execution", "sa_specificity_score": 0.5}},
        ])
        r = compute_outcomes(sid)
        assert r["phase_transitions"] == 2
        assert r["avg_specificity"] == round((0.1 + 0.3 + 0.5) / 3, 3)

    def test_context_dependency_distribution(self, db):
        sid = "deps"
        self._insert(db, sid, [
            {"id": "p1", "type": "user_prompt", "ts": 1.0,
             "metadata": {"sa_context_dependency": "low"}},
            {"id": "p2", "type": "user_prompt", "ts": 2.0,
             "metadata": {"sa_context_dependency": "high"}},
            {"id": "p3", "type": "user_prompt", "ts": 3.0,
             "metadata": {"sa_context_dependency": "high"}},
        ])
        r = compute_outcomes(sid)
        assert r["context_dependency_dist"]["low"] == 1
        assert r["context_dependency_dist"]["high"] == 2


# ===================================================================
# Performance
# ===================================================================


class TestPerformance:
    def test_analyze_prompt_speed(self):
        """analyze_prompt must complete in <50ms for a large prompt."""
        text = (
            "Fix the auth bug in src/api/routes/sessions.py line 42. "
            "The TypeError occurs when session_id is None. "
            "Make sure the endpoint returns 404 instead of crashing. "
        ) * 50  # ~2400 words

        start = time.perf_counter()
        iterations = 50
        for _ in range(iterations):
            analyze_prompt(text)
        elapsed_ms = (time.perf_counter() - start) / iterations * 1000

        assert elapsed_ms < 50, f"analyze_prompt took {elapsed_ms:.1f}ms (limit: 50ms)"
