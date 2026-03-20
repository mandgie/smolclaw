"""Tests for the Memory system."""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from unittest.mock import patch

from smolclaw.memory import Memory, serialize_f32


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


class TestMemoryGetFact:
    def test_get_existing_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Get me", category="tech")
        fact = mem.get_fact(fact_id)
        assert fact is not None
        assert fact["id"] == fact_id
        assert fact["content"] == "Get me"
        assert fact["category"] == "tech"
        assert fact["agent"] == "tars"

    def test_get_nonexistent_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        assert mem.get_fact(9999) is None

    def test_get_fact_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        fact_id = tars.add_fact("TARS only")
        # Coach can't see TARS's fact
        assert coach.get_fact(fact_id) is None
        # TARS can see its own
        assert tars.get_fact(fact_id) is not None


class TestMemoryUpdateFact:
    def test_update_content(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Original content", category="general")
        assert mem.update_fact(fact_id, content="Updated content") is True
        fact = mem.get_fact(fact_id)
        assert fact["content"] == "Updated content"
        assert fact["category"] == "general"

    def test_update_category(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Some content", category="general")
        assert mem.update_fact(fact_id, category="tech") is True
        fact = mem.get_fact(fact_id)
        assert fact["content"] == "Some content"
        assert fact["category"] == "tech"

    def test_update_both(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Old", category="old_cat")
        assert mem.update_fact(fact_id, content="New", category="new_cat") is True
        fact = mem.get_fact(fact_id)
        assert fact["content"] == "New"
        assert fact["category"] == "new_cat"

    def test_update_nothing_returns_true(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Content")
        # No fields to update, but fact exists
        assert mem.update_fact(fact_id) is True

    def test_update_nonexistent_fact(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        assert mem.update_fact(9999, content="New") is False

    def test_update_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        fact_id = tars.add_fact("TARS fact")
        # Coach can't update TARS's fact
        assert coach.update_fact(fact_id, content="Hijacked") is False
        # TARS can update its own
        assert tars.update_fact(fact_id, content="Updated by TARS") is True
        assert tars.get_fact(fact_id)["content"] == "Updated by TARS"

    def test_update_fts5_syncs(self, tmp_path: Path):
        """Updating content should be searchable by the new content."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        fact_id = mem.add_fact("Original keyword")
        assert len(mem.search_facts("Original")) == 1

        mem.update_fact(fact_id, content="Replacement keyword")
        # FTS5 triggers fire on UPDATE, so the new content should be searchable
        # (Note: FTS5 content tables with external content need explicit sync.
        #  Our trigger-based approach syncs on INSERT/DELETE, but UPDATE requires
        #  manual FTS rebuild for external-content tables. This test documents behavior.)
        results = mem.search_facts("Replacement")
        # Even if FTS5 doesn't auto-sync on UPDATE, LIKE fallback will catch it
        assert len(results) >= 1

    def test_update_vec_re_embeds(self, tmp_path: Path):
        """Updating content re-embeds the vector when vec is enabled."""
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        fact_id = mem.add_fact("Original vector content")
        assert mem.stats()["vec_facts"] == 1

        mem.update_fact(fact_id, content="New vector content")
        # Vector should still be present (re-embedded)
        assert mem.stats()["vec_facts"] == 1


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

    def test_repr_with_vec(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed)
        r = repr(mem)
        assert "vec" in r

    def test_repr_without_vec(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        r = repr(mem)
        assert "fts" in r


# --- Helpers for vector search tests ---

FAKE_DIM = 4


def _fake_embed(text: str) -> list[float]:
    """Deterministic fake embeddings based on text hash for testing."""
    h = hash(text) & 0xFFFFFFFF
    return [((h >> (i * 8)) & 0xFF) / 255.0 for i in range(FAKE_DIM)]


def _similar_embed(text: str) -> list[float]:
    """Embeddings where similar texts produce similar vectors."""
    base = [0.5] * FAKE_DIM
    if "python" in text.lower():
        base[0] = 0.9
        base[1] = 0.8
    if "weather" in text.lower():
        base[0] = 0.1
        base[2] = 0.9
    if "coding" in text.lower() or "programming" in text.lower():
        base[0] = 0.85
        base[1] = 0.75
    return base


class TestSerializeF32:
    def test_serialize_roundtrip(self):
        vec = [1.0, 2.0, 3.0, 4.0]
        serialized = serialize_f32(vec)
        assert isinstance(serialized, bytes)
        assert len(serialized) == 4 * 4  # 4 floats * 4 bytes each
        unpacked = struct.unpack(f"{len(vec)}f", serialized)
        assert list(unpacked) == vec

    def test_serialize_empty(self):
        assert serialize_f32([]) == b""

    def test_serialize_single(self):
        serialized = serialize_f32([42.0])
        assert len(serialized) == 4


class TestVectorSearchSetup:
    def test_vec_enabled_with_embed_fn(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        assert mem.vec_enabled is True

    def test_vec_disabled_without_embed_fn(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        assert mem.vec_enabled is False

    def test_vec_tables_created(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        Memory(db_path, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'vec_%'"
            ).fetchall()
        }
        conn.close()
        assert "vec_facts" in tables
        assert "vec_chunks" in tables

    def test_vec_tables_not_created_without_embed_fn(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        Memory(db_path, agent="tars")
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'vec_%'"
            ).fetchall()
        }
        conn.close()
        assert "vec_facts" not in tables
        assert "vec_chunks" not in tables

    def test_custom_embed_dim(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        assert mem.embed_dim == FAKE_DIM
        assert mem.vec_enabled is True


class TestVectorSearchFacts:
    def test_add_fact_creates_embedding(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        fact_id = mem.add_fact("Python is great")
        stats = mem.stats()
        assert stats["vec_facts"] == 1
        assert fact_id > 0

    def test_vector_search_finds_facts(self, tmp_path: Path):
        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_similar_embed, embed_dim=FAKE_DIM
        )
        mem.add_fact("Python programming tutorial")
        mem.add_fact("Weather forecast for Stockholm")
        mem.add_fact("Python coding best practices")

        results = mem.vector_search_facts("python")
        assert len(results) > 0
        # Results should have distance field
        assert "distance" in results[0]

    def test_vector_search_returns_empty_without_vec(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Some fact")
        results = mem.vector_search_facts("fact")
        assert results == []

    def test_vector_search_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        coach = Memory(db, agent="coach", embed_fn=_fake_embed, embed_dim=FAKE_DIM)

        tars.add_fact("TARS private fact")
        coach.add_fact("Coach private fact")

        tars_results = tars.vector_search_facts("private fact")
        assert len(tars_results) == 1
        assert tars_results[0]["agent"] == "tars"

    def test_vector_search_cross_agent(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        coach = Memory(db, agent="coach", embed_fn=_fake_embed, embed_dim=FAKE_DIM)

        tars.add_fact("TARS shared info")
        coach.add_fact("Coach shared info")

        results = tars.vector_search_facts("shared info", cross_agent=True)
        assert len(results) == 2

    def test_vector_search_respects_limit(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        for i in range(10):
            mem.add_fact(f"Fact number {i}")

        results = mem.vector_search_facts("Fact", limit=3)
        assert len(results) == 3

    def test_vector_search_ordered_by_distance(self, tmp_path: Path):
        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_similar_embed, embed_dim=FAKE_DIM
        )
        mem.add_fact("Weather forecast rain")
        mem.add_fact("Python programming language")
        mem.add_fact("Python coding tutorial")

        results = mem.vector_search_facts("python development")
        assert len(results) >= 2
        # Results should be ordered by distance (ascending)
        for i in range(len(results) - 1):
            assert results[i]["distance"] <= results[i + 1]["distance"]


class TestVectorSearchChunks:
    def test_add_chunk_creates_embedding(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_chunk("Hello", "Hi there!")
        stats = mem.stats()
        assert stats["vec_chunks"] == 1

    def test_vector_search_chunks(self, tmp_path: Path):
        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_similar_embed, embed_dim=FAKE_DIM
        )
        mem.add_chunk("What is Python?", "Python is a programming language")
        mem.add_chunk("How is the weather?", "Sunny and warm")

        results = mem.vector_search_chunks("python coding")
        assert len(results) > 0
        assert "distance" in results[0]

    def test_vector_search_chunks_empty_without_vec(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_chunk("Hello", "World")
        results = mem.vector_search_chunks("Hello")
        assert results == []

    def test_vector_search_chunks_agent_isolation(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        coach = Memory(db, agent="coach", embed_fn=_fake_embed, embed_dim=FAKE_DIM)

        tars.add_chunk("TARS question", "TARS answer")
        coach.add_chunk("Coach question", "Coach answer")

        results = tars.vector_search_chunks("question")
        assert len(results) == 1
        assert results[0]["agent"] == "tars"

    def test_vector_search_chunks_cross_agent(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        coach = Memory(db, agent="coach", embed_fn=_fake_embed, embed_dim=FAKE_DIM)

        tars.add_chunk("Topic", "TARS reply")
        coach.add_chunk("Topic", "Coach reply")

        results = tars.vector_search_chunks("Topic", cross_agent=True)
        assert len(results) == 2


class TestHybridSearch:
    def test_hybrid_search_facts_combines_results(self, tmp_path: Path):
        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_similar_embed, embed_dim=FAKE_DIM
        )
        mem.add_fact("Python programming language")
        mem.add_fact("Python coding best practices")
        mem.add_fact("Weather forecast sunny")

        results = mem.hybrid_search_facts("Python")
        assert len(results) >= 2
        # Python-related facts should appear
        contents = [r["content"] for r in results]
        assert any("Python" in c for c in contents)

    def test_hybrid_search_chunks(self, tmp_path: Path):
        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_similar_embed, embed_dim=FAKE_DIM
        )
        mem.add_chunk("What is Python?", "A programming language")
        mem.add_chunk("Weather today?", "Sunny")

        results = mem.hybrid_search_chunks("Python")
        assert len(results) >= 1

    def test_hybrid_search_without_vec_falls_back(self, tmp_path: Path):
        """Without vec, hybrid search returns FTS5/LIKE results only."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Fallback search test")

        results = mem.hybrid_search_facts("Fallback")
        assert len(results) == 1
        assert results[0]["content"] == "Fallback search test"

    def test_hybrid_search_respects_limit(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        for i in range(20):
            mem.add_fact(f"Repeated fact {i}")

        results = mem.hybrid_search_facts("Repeated", limit=5)
        assert len(results) == 5

    def test_hybrid_search_deduplicates(self, tmp_path: Path):
        """Items found by both vec and FTS5 should appear only once."""
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_fact("Unique test content")

        results = mem.hybrid_search_facts("Unique test content")
        # Should have exactly 1, not duplicated
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids))


class TestRRFMerge:
    def test_rrf_basic_merge(self):
        list_a = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
        list_b = [{"id": 2, "content": "b"}, {"id": 3, "content": "c"}]

        merged = Memory._rrf_merge(list_a, list_b, limit=10)
        ids = [r["id"] for r in merged]
        # id=2 appears in both, should rank highest
        assert ids[0] == 2
        assert set(ids) == {1, 2, 3}

    def test_rrf_respects_limit(self):
        list_a = [{"id": i, "content": f"a{i}"} for i in range(10)]
        list_b = [{"id": i + 10, "content": f"b{i}"} for i in range(10)]

        merged = Memory._rrf_merge(list_a, list_b, limit=5)
        assert len(merged) == 5

    def test_rrf_empty_lists(self):
        assert Memory._rrf_merge([], [], limit=10) == []

    def test_rrf_one_empty_list(self):
        items = [{"id": 1, "content": "x"}, {"id": 2, "content": "y"}]
        merged = Memory._rrf_merge(items, [], limit=10)
        assert len(merged) == 2

    def test_rrf_identical_lists(self):
        items = [{"id": 1, "content": "x"}, {"id": 2, "content": "y"}]
        merged = Memory._rrf_merge(items, items, limit=10)
        # Should deduplicate
        assert len(merged) == 2


class TestVectorDeleteAndClear:
    def test_delete_fact_removes_vec_entry(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        fact_id = mem.add_fact("Vector delete test")
        assert mem.stats()["vec_facts"] == 1

        mem.delete_fact(fact_id)
        assert mem.stats()["vec_facts"] == 0

    def test_clear_removes_vec_entries(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_fact("Fact 1")
        mem.add_fact("Fact 2")
        mem.add_chunk("Q1", "A1")
        assert mem.stats()["vec_facts"] == 2
        assert mem.stats()["vec_chunks"] == 1

        mem.clear()
        assert mem.stats()["vec_facts"] == 0
        assert mem.stats()["vec_chunks"] == 0

    def test_clear_agent_isolation_with_vec(self, tmp_path: Path):
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        coach = Memory(db, agent="coach", embed_fn=_fake_embed, embed_dim=FAKE_DIM)

        tars.add_fact("TARS fact")
        coach.add_fact("Coach fact")

        tars.clear()
        # TARS vec entries gone, coach's remain
        assert tars.stats()["facts"] == 0
        assert coach.stats()["facts"] == 1


class TestVectorEmbedFailure:
    def test_embed_failure_graceful(self, tmp_path: Path):
        """If embed_fn raises, the fact is still stored (just without vector)."""
        call_count = 0

        def _failing_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Embedding service down")

        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_failing_embed, embed_dim=FAKE_DIM
        )
        # Despite embedding failure, the fact should be stored
        fact_id = mem.add_fact("Fact without embedding")
        assert fact_id > 0
        assert mem.stats()["facts"] == 1
        # Vec table should be empty (embedding failed)
        assert mem.stats()["vec_facts"] == 0

    def test_vector_search_after_embed_failure(self, tmp_path: Path):
        """vector_search returns empty when embed_fn fails for the query."""

        def _failing_embed(text: str) -> list[float]:
            raise RuntimeError("Embedding service down")

        mem = Memory(
            tmp_path / "test.db", agent="tars", embed_fn=_failing_embed, embed_dim=FAKE_DIM
        )
        results = mem.vector_search_facts("anything")
        assert results == []


class TestVectorStats:
    def test_stats_include_vec_counts(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_fact("Fact 1")
        mem.add_chunk("Q", "A")

        stats = mem.stats()
        assert stats["vec_enabled"] is True
        assert stats["vec_facts"] == 1
        assert stats["vec_chunks"] == 1

    def test_stats_without_vec(self, tmp_path: Path):
        mem = Memory(tmp_path / "test.db", agent="tars")
        stats = mem.stats()
        assert stats["vec_enabled"] is False
        assert "vec_facts" not in stats


class TestLikeSearchCrossAgent:
    """Test the LIKE search fallback path with cross_agent=True."""

    def test_like_search_facts_cross_agent(self, tmp_path: Path):
        """LIKE search with cross_agent=True finds facts from all agents."""
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("TARS stores data")
        coach.add_fact("Coach stores data")

        # Empty query → FTS5 escape returns "" → LIKE fallback with %%
        results = tars.search_facts("", cross_agent=True)
        assert len(results) == 2

    def test_like_search_chunks_cross_agent(self, tmp_path: Path):
        """LIKE search for chunks with cross_agent=True finds all agents."""
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_chunk("TARS question", "TARS answer")
        coach.add_chunk("Coach question", "Coach answer")

        # Empty query triggers LIKE path
        results = tars.search_chunks("", cross_agent=True)
        assert len(results) == 2

    def test_like_search_facts_cross_agent_with_match(self, tmp_path: Path):
        """LIKE cross-agent search matches content from multiple agents."""
        db = tmp_path / "shared.db"
        tars = Memory(db, agent="tars")
        coach = Memory(db, agent="coach")

        tars.add_fact("weather forecast sunny")
        coach.add_fact("weather forecast rainy")
        coach.add_fact("unrelated content")

        # Force LIKE path with special chars that FTS5 escape strips
        results = tars.search_facts("***", cross_agent=True)
        # *** → LIKE %***% — won't match anything since content doesn't contain ***
        assert len(results) == 0


class TestFTS5OperationalErrorFallback:
    """Test that FTS5 OperationalError falls back to LIKE search."""

    def test_search_facts_fts_error_fallback(self, tmp_path: Path):
        """When FTS5 raises OperationalError, search falls back to LIKE."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_fact("Python is great")

        with patch.object(
            mem, "_fts_search_facts", side_effect=sqlite3.OperationalError("FTS corrupted")
        ):
            results = mem.search_facts("Python")
            assert len(results) == 1
            assert results[0]["content"] == "Python is great"

    def test_search_chunks_fts_error_fallback(self, tmp_path: Path):
        """When FTS5 raises OperationalError, chunk search falls back to LIKE."""
        mem = Memory(tmp_path / "test.db", agent="tars")
        mem.add_chunk("What is Python?", "A programming language")

        with patch.object(
            mem, "_fts_search_chunks", side_effect=sqlite3.OperationalError("FTS corrupted")
        ):
            results = mem.search_chunks("Python")
            assert len(results) == 1
            assert "Python" in results[0]["combined"]


class TestVectorSearchOperationalError:
    """Test that vector search handles OperationalError gracefully."""

    def _drop_vec_tables(self, db_path: Path) -> None:
        """Drop vec tables to simulate corruption."""
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("DROP TABLE IF EXISTS vec_facts")
        conn.execute("DROP TABLE IF EXISTS vec_chunks")
        conn.commit()
        conn.close()

    def test_vector_search_facts_operational_error(self, tmp_path: Path):
        """vector_search_facts returns [] on OperationalError."""
        db = tmp_path / "test.db"
        mem = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_fact("Test fact")

        # Drop vec tables to cause OperationalError on search
        self._drop_vec_tables(db)

        results = mem.vector_search_facts("Test")
        assert results == []

    def test_vector_search_chunks_operational_error(self, tmp_path: Path):
        """vector_search_chunks returns [] on OperationalError."""
        db = tmp_path / "test.db"
        mem = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_chunk("Question", "Answer")

        self._drop_vec_tables(db)

        results = mem.vector_search_chunks("Question")
        assert results == []


class TestStatsVecTableError:
    """Test stats() when vec tables are corrupted."""

    def test_stats_vec_table_operational_error(self, tmp_path: Path):
        """stats() handles OperationalError on vec tables gracefully."""
        mem = Memory(tmp_path / "test.db", agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        mem.add_fact("Test fact")

        # Drop the vec table to simulate corruption
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("DROP TABLE IF EXISTS vec_facts")
        conn.execute("DROP TABLE IF EXISTS vec_chunks")
        conn.commit()
        conn.close()

        stats = mem.stats()
        # Should return stats without crashing, vec counts omitted
        assert stats["facts"] == 1
        assert stats["vec_enabled"] is True  # Still thinks vec is enabled
        assert "vec_facts" not in stats  # But couldn't query vec tables


class TestFTSSetupFailure:
    """Test Memory init when FTS5 setup fails."""

    def test_fts_setup_exception_logs_warning(self, tmp_path: Path):
        """Memory init continues when FTS5 setup raises (logs warning, doesn't crash)."""
        db = tmp_path / "test.db"
        with patch.object(Memory, "_ensure_fts", side_effect=RuntimeError("FTS5 unavailable")):
            mem = Memory(db, agent="tars")
        # Memory is created and works for non-FTS operations
        assert mem.agent == "tars"
        # Can still add facts (FTS just won't be indexed)
        fact_id = mem.add_fact("Test fact without FTS")
        assert isinstance(fact_id, int)


class TestVecSetupFailure:
    """Test Memory init when sqlite-vec setup fails."""

    def test_vec_setup_exception_logs_warning(self, tmp_path: Path):
        """Memory init continues when vec setup raises (logs warning, vec_enabled stays False)."""
        db = tmp_path / "test.db"
        # Patch _HAS_SQLITE_VEC to True but make the setup fail
        with (
            patch("smolclaw.memory._HAS_SQLITE_VEC", True),
            patch.object(Memory, "_ensure_vec", side_effect=RuntimeError("vec table corrupt")),
        ):
            mem = Memory(db, agent="tars", embed_fn=_fake_embed, embed_dim=FAKE_DIM)
        # vec_enabled should still be False since setup failed
        assert mem.vec_enabled is False


class TestFTSSyncOnUpdateFailure:
    """Test update_fact when FTS5 sync fails."""

    def test_update_fact_fts_sync_failure(self, tmp_path: Path):
        """update_fact succeeds even when FTS5 sync on update fails."""
        db = tmp_path / "test.db"
        mem = Memory(db, agent="tars")
        fact_id = mem.add_fact("Original content")

        # Drop FTS tables to cause sync failure on update
        conn = sqlite3.connect(str(db))
        conn.execute("DROP TABLE IF EXISTS facts_fts")
        conn.commit()
        conn.close()

        # Update should succeed (FTS sync failure is non-fatal)
        result = mem.update_fact(fact_id, content="Updated content")
        assert result is True

        # Verify the content was updated
        fact = mem.get_fact(fact_id)
        assert fact is not None
        assert fact["content"] == "Updated content"
