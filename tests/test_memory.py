"""Tests for the Memory system."""

from __future__ import annotations

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
