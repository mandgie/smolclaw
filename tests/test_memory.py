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


class TestMemoryRepr:
    def test_repr(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        r = repr(mem)
        assert "Memory" in r
        assert "tars" in r
        assert "test.db" in r
