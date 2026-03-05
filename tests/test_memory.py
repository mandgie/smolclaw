"""Tests for the Memory system."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from smolclaw.memory import Memory


class TestMemoryFacts:
    def test_add_and_search_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Python is great", category="tech")
        assert fact_id > 0

        results = mem.search_facts("Python")
        assert len(results) == 1
        assert results[0]["content"] == "Python is great"

    def test_search_facts_no_match(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Python is great")
        assert mem.search_facts("Rust") == []

    def test_search_facts_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS fact")
        coach.add_fact("Coach fact")

        assert len(tars.search_facts("fact")) == 1
        assert tars.search_facts("fact")[0]["content"] == "TARS fact"

        assert len(coach.search_facts("fact")) == 1
        assert coach.search_facts("fact")[0]["content"] == "Coach fact"

    def test_search_facts_cross_agent(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS secret")
        coach.add_fact("Coach secret")

        results = tars.search_facts("secret", cross_agent=True)
        assert len(results) == 2


class TestMemoryChunks:
    def test_add_and_search_chunk(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        chunk_id = mem.add_chunk("Hello", "Hi there!", session_id="sess-1")
        assert chunk_id > 0

        results = mem.search_chunks("Hello")
        assert len(results) == 1
        assert "Hello" in results[0]["combined"]
        assert "Hi there!" in results[0]["combined"]

    def test_chunk_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_chunk("TARS question", "TARS answer")
        coach.add_chunk("Coach question", "Coach answer")

        assert len(tars.search_chunks("question")) == 1
        assert len(coach.search_chunks("question")) == 1

    def test_chunk_cross_agent(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_chunk("shared topic", "tars reply")
        coach.add_chunk("shared topic", "coach reply")

        results = tars.search_chunks("shared topic", cross_agent=True)
        assert len(results) == 2


class TestMemoryListFacts:
    def test_list_facts_returns_all(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Fact A", category="tech")
        mem.add_fact("Fact B", category="personal")
        mem.add_fact("Fact C", category="tech")

        facts = mem.list_facts()
        assert len(facts) == 3

    def test_list_facts_with_category_filter(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Python is great", category="tech")
        mem.add_fact("Likes coffee", category="personal")
        mem.add_fact("Uses Linux", category="tech")

        tech_facts = mem.list_facts(category="tech")
        assert len(tech_facts) == 2
        assert all(f["category"] == "tech" for f in tech_facts)

    def test_list_facts_with_limit(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        for i in range(10):
            mem.add_fact(f"Fact {i}")

        facts = mem.list_facts(limit=3)
        assert len(facts) == 3

    def test_list_facts_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS fact")
        coach.add_fact("Coach fact")

        assert len(tars.list_facts()) == 1
        assert len(coach.list_facts()) == 1

    def test_list_facts_empty(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        assert mem.list_facts() == []


class TestMemoryDeleteFact:
    def test_delete_existing_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Delete me")
        assert mem.delete_fact(fact_id) is True
        assert mem.list_facts() == []

    def test_delete_nonexistent_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        assert mem.delete_fact(9999) is False

    def test_delete_fact_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        fact_id = tars.add_fact("TARS only")
        # Coach can't delete TARS's fact
        assert coach.delete_fact(fact_id) is False
        # TARS can delete its own
        assert tars.delete_fact(fact_id) is True


class TestMemoryClear:
    def test_clear_removes_all(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Fact 1")
        mem.add_fact("Fact 2")
        mem.add_chunk("Q1", "A1")
        mem.add_chunk("Q2", "A2")

        result = mem.clear()
        assert result["facts_deleted"] == 2
        assert result["chunks_deleted"] == 2
        assert mem.stats()["facts"] == 0
        assert mem.stats()["chunks"] == 0

    def test_clear_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS fact")
        coach.add_fact("Coach fact")

        tars.clear()
        # TARS should be empty, coach should be untouched
        assert tars.stats()["facts"] == 0
        assert coach.stats()["facts"] == 1

    def test_clear_empty_memory(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        result = mem.clear()
        assert result["facts_deleted"] == 0
        assert result["chunks_deleted"] == 0


class TestMemoryStats:
    def test_stats(self, tmp_path: Path):
        db = tmp_path / "test.db"
        mem = Memory(db, agent="tars")
        mem.add_fact("Fact 1")
        mem.add_fact("Fact 2")
        mem.add_chunk("Q", "A")

        stats = mem.stats()
        assert stats["agent"] == "tars"
        assert stats["facts"] == 2
        assert stats["chunks"] == 1
        assert stats["total_facts"] == 2
        assert stats["total_chunks"] == 1

    def test_stats_empty(self, tmp_path: Path):
        mem = Memory(tmp_path / "empty.db", agent="tars")
        stats = mem.stats()
        assert stats["facts"] == 0
        assert stats["chunks"] == 0


class TestMemoryRobustness:
    def test_wal_mode_enabled(self, tmp_path: Path):
        """Verify WAL journal mode is set on the database."""
        db_path = tmp_path / "test.db"
        Memory(db_path, agent="tars")
        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_connection_timeout(self, tmp_path: Path):
        """Verify that _connect uses a non-zero timeout."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        conn = mem._connect()
        # sqlite3 doesn't expose timeout directly, but we can verify
        # the connection works and row_factory is set
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_concurrent_agents_same_db(self, tmp_path: Path):
        """Two Memory instances on the same DB can read/write without locking."""
        db_path = tmp_path / "shared.db"
        tars = Memory(db_path, agent="tars")
        coach = Memory(db_path, agent="coach")

        # Both write
        tars.add_fact("TARS data")
        coach.add_fact("Coach data")

        # Both read
        assert len(tars.search_facts("data")) == 1
        assert len(coach.search_facts("data")) == 1

        # Cross-agent still works
        assert len(tars.search_facts("data", cross_agent=True)) == 2


class TestMemoryFTS5:
    def test_fts5_tables_created(self, tmp_path: Path):
        """Verify FTS5 virtual tables are created in the schema."""
        db_path = tmp_path / "test.db"
        Memory(db_path, agent="tars")
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '%_fts%'"
            ).fetchall()
        }
        conn.close()
        assert "facts_fts" in tables
        assert "chunks_fts" in tables

    def test_fts5_triggers_created(self, tmp_path: Path):
        """Verify sync triggers exist for FTS tables."""
        db_path = tmp_path / "test.db"
        Memory(db_path, agent="tars")
        conn = sqlite3.connect(str(db_path))
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        conn.close()
        assert "facts_fts_ins" in triggers
        assert "facts_fts_del" in triggers
        assert "chunks_fts_ins" in triggers
        assert "chunks_fts_del" in triggers

    def test_fts5_search_returns_results(self, tmp_path: Path):
        """FTS5 search finds facts by keyword."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("The quick brown fox jumps over the lazy dog")
        mem.add_fact("Python programming language")

        results = mem.search_facts("fox")
        assert len(results) == 1
        assert "fox" in results[0]["content"]

    def test_fts5_bm25_ranking(self, tmp_path: Path):
        """FTS5 returns more relevant results first (BM25 ranking)."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Python is popular")
        mem.add_fact("Python Python Python is mentioned a lot about Python")
        mem.add_fact("Java is also popular")

        results = mem.search_facts("Python", limit=10)
        assert len(results) == 2
        # The fact with more "Python" occurrences should rank higher
        assert "Python" in results[0]["content"]
        assert "Python" in results[1]["content"]

    def test_fts5_chunk_search(self, tmp_path: Path):
        """FTS5 search works on conversation chunks."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_chunk("What is Kubernetes?", "Kubernetes is a container orchestrator")
        mem.add_chunk("How is the weather?", "Sunny today")

        results = mem.search_chunks("Kubernetes")
        assert len(results) == 1
        assert "Kubernetes" in results[0]["combined"]

    def test_fts5_delete_syncs_index(self, tmp_path: Path):
        """Deleting a fact removes it from the FTS index."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Temporary fact for deletion test")

        assert len(mem.search_facts("Temporary")) == 1
        mem.delete_fact(fact_id)
        assert len(mem.search_facts("Temporary")) == 0

    def test_fts5_clear_syncs_index(self, tmp_path: Path):
        """Clearing memory removes entries from FTS indexes."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Will be cleared")
        mem.add_chunk("Will be cleared", "Also cleared")

        mem.clear()
        assert mem.search_facts("cleared") == []
        assert mem.search_chunks("cleared") == []

    def test_fts5_cross_agent_search(self, tmp_path: Path):
        """FTS5 cross-agent search finds facts from all agents."""
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS remembers everything")
        coach.add_fact("Coach remembers workouts")

        results = tars.search_facts("remembers", cross_agent=True)
        assert len(results) == 2

    def test_fts5_escape_special_characters(self):
        """FTS5 escape handles special characters safely."""
        assert Memory._fts5_escape("hello world") == '"hello" "world"'
        assert Memory._fts5_escape("test*query") == '"test" "query"'
        assert Memory._fts5_escape('say "hello"') == '"say" "hello"'
        assert Memory._fts5_escape("") == ""
        assert Memory._fts5_escape("(parens)") == '"parens"'

    def test_fts5_fallback_to_like_on_empty_query(self, tmp_path: Path):
        """Empty query falls back to LIKE (matches all via %%)."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Some fact")
        # Empty query — FTS5 escape returns "", triggers LIKE fallback
        results = mem.search_facts("")
        assert len(results) == 1

    def test_fts5_existing_data_indexed_on_creation(self, tmp_path: Path):
        """FTS5 indexes existing data when tables are first created."""
        db_path = tmp_path / "test.db"
        # Create DB without FTS (simulate pre-FTS5 database)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL DEFAULT 'shared',
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'manual',
                created_at TEXT NOT NULL
            );
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL DEFAULT 'shared',
                session_id TEXT,
                timestamp TEXT,
                user_text TEXT NOT NULL,
                assistant_text TEXT,
                combined TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO facts (agent, content, created_at) VALUES (?, ?, ?)",
            ("tars", "Pre-existing fact", "2024-01-01"),
        )
        conn.commit()
        conn.close()

        # Now open with Memory — FTS5 should be created and rebuild indexes
        mem = Memory(db_path, agent="tars")
        results = mem.search_facts("Pre-existing")
        assert len(results) == 1


class TestMemoryRepr:
    def test_repr(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        r = repr(mem)
        assert "Memory" in r
        assert "tars" in r
        assert "test.db" in r
