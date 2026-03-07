"""Namespaced memory system — shared SQLite DB with per-agent scoping.

Supports three search tiers (best available is used automatically):
1. Vector search via sqlite-vec (semantic similarity, requires embed_fn)
2. FTS5 full-text search (BM25 ranking)
3. LIKE search (fallback)

Hybrid search combines vector + FTS5 results with reciprocal rank fusion.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger("smolclaw")

__all__ = ["Memory", "serialize_f32"]

# Type alias for embedding functions: text -> list of floats
EmbedFn = Callable[[str], list[float]]

# Try to import sqlite-vec; graceful if missing
try:
    import sqlite_vec

    _HAS_SQLITE_VEC = True
except ImportError:
    _HAS_SQLITE_VEC = False


def serialize_f32(vec: list[float]) -> bytes:
    """Serialize a list of floats to bytes for sqlite-vec storage."""
    return struct.pack(f"{len(vec)}f", *vec)


class Memory:
    """Agent-namespaced memory backed by SQLite.

    All agents share one memory.db. Each entry is tagged with an agent name.
    Agents query their own namespace by default, with optional cross-agent search.

    When sqlite-vec is installed and an embed_fn is provided, vector search
    is available for semantic similarity queries. Otherwise, FTS5/LIKE is used.
    """

    def __init__(
        self,
        db_path: Path,
        agent: str = "shared",
        embed_fn: EmbedFn | None = None,
        embed_dim: int = 256,
    ):
        """Initialize memory for an agent, creating tables if needed.

        Args:
            db_path: Path to the shared SQLite database file.
            agent: Agent name used to namespace all stored data.
            embed_fn: Optional callable that takes text and returns a float vector.
                      When provided with sqlite-vec, enables semantic vector search.
            embed_dim: Dimensionality of the embedding vectors (default: 256).
        """
        self.db_path = db_path
        self.agent = agent
        self.embed_fn = embed_fn
        self.embed_dim = embed_dim
        self.vec_enabled = False
        self._ensure_schema()

    def __repr__(self) -> str:
        vec_status = "vec" if self.vec_enabled else "fts"
        return f"Memory(agent={self.agent!r}, db={self.db_path}, mode={vec_status})"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        if self.vec_enabled:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        return conn

    def _ensure_schema(self) -> None:
        """Create tables, indexes, FTS5, and optionally vec0 tables."""
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent      TEXT NOT NULL DEFAULT 'shared',
                    content    TEXT NOT NULL,
                    category   TEXT DEFAULT 'general',
                    source     TEXT DEFAULT 'manual',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent          TEXT NOT NULL DEFAULT 'shared',
                    session_id     TEXT,
                    timestamp      TEXT,
                    user_text      TEXT NOT NULL,
                    assistant_text TEXT,
                    combined       TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_facts_agent ON facts(agent);
                CREATE INDEX IF NOT EXISTS idx_chunks_agent ON chunks(agent);
            """)
            try:
                self._ensure_fts(conn)
            except Exception as e:
                log.warning(f"FTS5 setup skipped: {e}")

            if _HAS_SQLITE_VEC and self.embed_fn is not None:
                try:
                    conn.enable_load_extension(True)
                    sqlite_vec.load(conn)
                    conn.enable_load_extension(False)
                    self._ensure_vec(conn)
                    self.vec_enabled = True
                    log.info(f"Vector search enabled for {self.agent} ({self.embed_dim}d)")
                except Exception as e:
                    log.warning(f"Vector search setup skipped: {e}")
        finally:
            conn.close()

    def _ensure_fts(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual tables and sync triggers (idempotent)."""
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name IN ('facts_fts', 'chunks_fts')"
            ).fetchall()
        }

        if "facts_fts" not in existing:
            conn.execute(
                "CREATE VIRTUAL TABLE facts_fts"
                " USING fts5(content, content=facts, content_rowid=id)"
            )
            conn.execute(
                "CREATE TRIGGER facts_fts_ins AFTER INSERT ON facts BEGIN"
                " INSERT INTO facts_fts(rowid, content) VALUES (new.id, new.content);"
                " END"
            )
            conn.execute(
                "CREATE TRIGGER facts_fts_del AFTER DELETE ON facts BEGIN"
                " INSERT INTO facts_fts(facts_fts, rowid, content)"
                " VALUES('delete', old.id, old.content);"
                " END"
            )
            conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")

        if "chunks_fts" not in existing:
            conn.execute(
                "CREATE VIRTUAL TABLE chunks_fts"
                " USING fts5(combined, content=chunks, content_rowid=id)"
            )
            conn.execute(
                "CREATE TRIGGER chunks_fts_ins AFTER INSERT ON chunks BEGIN"
                " INSERT INTO chunks_fts(rowid, combined) VALUES (new.id, new.combined);"
                " END"
            )
            conn.execute(
                "CREATE TRIGGER chunks_fts_del AFTER DELETE ON chunks BEGIN"
                " INSERT INTO chunks_fts(chunks_fts, rowid, combined)"
                " VALUES('delete', old.id, old.combined);"
                " END"
            )
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

        conn.commit()

    def _ensure_vec(self, conn: sqlite3.Connection) -> None:
        """Create sqlite-vec virtual tables for vector search (idempotent)."""
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name IN ('vec_facts', 'vec_chunks')"
            ).fetchall()
        }

        if "vec_facts" not in existing:
            conn.execute(
                f"CREATE VIRTUAL TABLE vec_facts USING vec0(embedding float[{self.embed_dim}])"
            )
        if "vec_chunks" not in existing:
            conn.execute(
                f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{self.embed_dim}])"
            )
        conn.commit()

    @staticmethod
    def _fts5_escape(query: str) -> str:
        """Escape a query for FTS5 MATCH — quote each token as a literal."""
        special = set('"*()^:+')
        cleaned = "".join(c if c not in special else " " for c in query)
        words = cleaned.split()
        if not words:
            return ""
        return " ".join(f'"{w}"' for w in words)

    def _embed(self, text: str) -> bytes | None:
        """Get embedding for text, returning serialized bytes or None."""
        if not self.vec_enabled or self.embed_fn is None:
            return None
        try:
            vec = self.embed_fn(text)
            return serialize_f32(vec)
        except Exception as e:
            log.warning(f"Embedding failed: {e}")
            return None

    # --- Facts ---

    def add_fact(self, content: str, category: str = "general", source: str = "manual") -> int:
        """Add a fact to this agent's namespace. Embeds for vector search if available."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT INTO facts (agent, content, category, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.agent, content, category, source, datetime.now().isoformat()),
            )
            fact_id = cursor.lastrowid
            embedding = self._embed(content)
            if embedding is not None:
                conn.execute(
                    "INSERT INTO vec_facts (rowid, embedding) VALUES (?, ?)",
                    (fact_id, embedding),
                )
            conn.commit()
            return fact_id
        finally:
            conn.close()

    def search_facts(self, query: str, limit: int = 10, cross_agent: bool = False) -> list[dict]:
        """Search facts using best available method (vector > FTS5 > LIKE)."""
        conn = self._connect()
        try:
            fts_query = self._fts5_escape(query)
            if fts_query:
                try:
                    return self._fts_search_facts(conn, fts_query, limit, cross_agent)
                except sqlite3.OperationalError:
                    pass
            return self._like_search_facts(conn, query, limit, cross_agent)
        finally:
            conn.close()

    def vector_search_facts(
        self, query: str, limit: int = 10, cross_agent: bool = False
    ) -> list[dict]:
        """Search facts using vector similarity. Returns results with distance scores.

        Requires sqlite-vec and embed_fn. Returns empty list if not available.
        """
        embedding = self._embed(query)
        if embedding is None:
            return []
        conn = self._connect()
        try:
            if cross_agent:
                rows = conn.execute(
                    "SELECT f.*, v.distance FROM vec_facts v"
                    " JOIN facts f ON f.id = v.rowid"
                    " WHERE v.embedding MATCH ? AND k = ?"
                    " ORDER BY v.distance",
                    (embedding, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT f.*, v.distance FROM vec_facts v"
                    " JOIN facts f ON f.id = v.rowid"
                    " WHERE v.embedding MATCH ? AND k = ? AND f.agent = ?"
                    " ORDER BY v.distance",
                    (embedding, limit, self.agent),
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            log.warning(f"Vector search failed: {e}")
            return []
        finally:
            conn.close()

    def hybrid_search_facts(
        self, query: str, limit: int = 10, cross_agent: bool = False
    ) -> list[dict]:
        """Combine vector + FTS5 results using reciprocal rank fusion.

        Falls back to FTS5-only if vector search is unavailable.
        """
        vec_results = self.vector_search_facts(query, limit=limit * 2, cross_agent=cross_agent)
        fts_results = self.search_facts(query, limit=limit * 2, cross_agent=cross_agent)
        return self._rrf_merge(vec_results, fts_results, limit)

    def _fts_search_facts(
        self, conn: sqlite3.Connection, fts_query: str, limit: int, cross_agent: bool
    ) -> list[dict]:
        if cross_agent:
            rows = conn.execute(
                "SELECT f.* FROM facts_fts"
                " JOIN facts f ON f.id = facts_fts.rowid"
                " WHERE facts_fts MATCH ?"
                " ORDER BY bm25(facts_fts) LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT f.* FROM facts_fts"
                " JOIN facts f ON f.id = facts_fts.rowid"
                " WHERE facts_fts MATCH ? AND f.agent = ?"
                " ORDER BY bm25(facts_fts) LIMIT ?",
                (fts_query, self.agent, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _like_search_facts(
        self, conn: sqlite3.Connection, query: str, limit: int, cross_agent: bool
    ) -> list[dict]:
        if cross_agent:
            rows = conn.execute(
                "SELECT * FROM facts WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM facts WHERE agent = ? AND content LIKE ?"
                " ORDER BY created_at DESC LIMIT ?",
                (self.agent, f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Chunks ---

    def add_chunk(
        self,
        user_text: str,
        assistant_text: str = "",
        session_id: str = "",
    ) -> int:
        """Store a conversation chunk. Embeds for vector search if available."""
        combined = f"User: {user_text}\nAssistant: {assistant_text}"
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT INTO chunks"
                " (agent, session_id, timestamp, user_text, assistant_text, combined)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.agent,
                    session_id,
                    datetime.now().isoformat(),
                    user_text,
                    assistant_text,
                    combined,
                ),
            )
            chunk_id = cursor.lastrowid
            embedding = self._embed(combined)
            if embedding is not None:
                conn.execute(
                    "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                    (chunk_id, embedding),
                )
            conn.commit()
            return chunk_id
        finally:
            conn.close()

    def search_chunks(self, query: str, limit: int = 10, cross_agent: bool = False) -> list[dict]:
        """Search conversation chunks using FTS5 with BM25 ranking.

        Falls back to LIKE search if FTS5 query fails.
        """
        conn = self._connect()
        try:
            fts_query = self._fts5_escape(query)
            if fts_query:
                try:
                    return self._fts_search_chunks(conn, fts_query, limit, cross_agent)
                except sqlite3.OperationalError:
                    pass
            return self._like_search_chunks(conn, query, limit, cross_agent)
        finally:
            conn.close()

    def vector_search_chunks(
        self, query: str, limit: int = 10, cross_agent: bool = False
    ) -> list[dict]:
        """Search chunks using vector similarity. Returns results with distance scores."""
        embedding = self._embed(query)
        if embedding is None:
            return []
        conn = self._connect()
        try:
            if cross_agent:
                rows = conn.execute(
                    "SELECT c.*, v.distance FROM vec_chunks v"
                    " JOIN chunks c ON c.id = v.rowid"
                    " WHERE v.embedding MATCH ? AND k = ?"
                    " ORDER BY v.distance",
                    (embedding, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT c.*, v.distance FROM vec_chunks v"
                    " JOIN chunks c ON c.id = v.rowid"
                    " WHERE v.embedding MATCH ? AND k = ? AND c.agent = ?"
                    " ORDER BY v.distance",
                    (embedding, limit, self.agent),
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            log.warning(f"Vector search failed: {e}")
            return []
        finally:
            conn.close()

    def hybrid_search_chunks(
        self, query: str, limit: int = 10, cross_agent: bool = False
    ) -> list[dict]:
        """Combine vector + FTS5 results using reciprocal rank fusion."""
        vec_results = self.vector_search_chunks(query, limit=limit * 2, cross_agent=cross_agent)
        fts_results = self.search_chunks(query, limit=limit * 2, cross_agent=cross_agent)
        return self._rrf_merge(vec_results, fts_results, limit)

    def _fts_search_chunks(
        self, conn: sqlite3.Connection, fts_query: str, limit: int, cross_agent: bool
    ) -> list[dict]:
        if cross_agent:
            rows = conn.execute(
                "SELECT c.* FROM chunks_fts"
                " JOIN chunks c ON c.id = chunks_fts.rowid"
                " WHERE chunks_fts MATCH ?"
                " ORDER BY bm25(chunks_fts) LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.* FROM chunks_fts"
                " JOIN chunks c ON c.id = chunks_fts.rowid"
                " WHERE chunks_fts MATCH ? AND c.agent = ?"
                " ORDER BY bm25(chunks_fts) LIMIT ?",
                (fts_query, self.agent, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _like_search_chunks(
        self, conn: sqlite3.Connection, query: str, limit: int, cross_agent: bool
    ) -> list[dict]:
        if cross_agent:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE combined LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE agent = ? AND combined LIKE ?"
                " ORDER BY timestamp DESC LIMIT ?",
                (self.agent, f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Hybrid search helpers ---

    @staticmethod
    def _rrf_merge(
        vec_results: list[dict], fts_results: list[dict], limit: int, k: int = 60
    ) -> list[dict]:
        """Reciprocal Rank Fusion — merge two ranked result lists.

        RRF score = sum(1 / (k + rank)) across lists where the item appears.
        Higher score = better. k=60 is the standard constant.
        """
        scores: dict[int, float] = {}
        items: dict[int, dict] = {}

        for rank, item in enumerate(vec_results):
            item_id = item["id"]
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            items[item_id] = item

        for rank, item in enumerate(fts_results):
            item_id = item["id"]
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            items[item_id] = item

        ranked = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [items[item_id] for item_id in ranked[:limit]]

    # --- List / Delete / Stats ---

    def list_facts(self, limit: int = 100, category: str | None = None) -> list[dict]:
        """List facts for this agent, optionally filtered by category."""
        conn = self._connect()
        try:
            if category:
                rows = conn.execute(
                    "SELECT * FROM facts WHERE agent = ? AND category = ?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (self.agent, category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM facts WHERE agent = ? ORDER BY created_at DESC LIMIT ?",
                    (self.agent, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_fact(self, fact_id: int) -> bool:
        """Delete a fact by ID (must belong to this agent). Returns True if deleted."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM facts WHERE id = ? AND agent = ?",
                (fact_id, self.agent),
            )
            if self.vec_enabled:
                conn.execute("DELETE FROM vec_facts WHERE rowid = ?", (fact_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def clear(self) -> dict[str, int]:
        """Clear all facts and chunks for this agent. Returns counts of deleted rows."""
        conn = self._connect()
        try:
            # Get IDs before deleting so we can clean up vec tables
            if self.vec_enabled:
                fact_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM facts WHERE agent = ?", (self.agent,)
                    ).fetchall()
                ]
                chunk_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM chunks WHERE agent = ?", (self.agent,)
                    ).fetchall()
                ]

            facts_deleted = conn.execute(
                "DELETE FROM facts WHERE agent = ?", (self.agent,)
            ).rowcount
            chunks_deleted = conn.execute(
                "DELETE FROM chunks WHERE agent = ?", (self.agent,)
            ).rowcount

            if self.vec_enabled:
                for fid in fact_ids:
                    conn.execute("DELETE FROM vec_facts WHERE rowid = ?", (fid,))
                for cid in chunk_ids:
                    conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (cid,))

            conn.commit()
            return {"facts_deleted": facts_deleted, "chunks_deleted": chunks_deleted}
        finally:
            conn.close()

    def stats(self) -> dict:
        """Return memory statistics: fact/chunk counts for this agent and globally."""
        conn = self._connect()
        try:
            facts_count = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE agent = ?", (self.agent,)
            ).fetchone()[0]
            chunks_count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE agent = ?", (self.agent,)
            ).fetchone()[0]
            total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

            result = {
                "agent": self.agent,
                "facts": facts_count,
                "chunks": chunks_count,
                "total_facts": total_facts,
                "total_chunks": total_chunks,
                "vec_enabled": self.vec_enabled,
            }

            if self.vec_enabled:
                try:
                    result["vec_facts"] = conn.execute("SELECT COUNT(*) FROM vec_facts").fetchone()[
                        0
                    ]
                    result["vec_chunks"] = conn.execute(
                        "SELECT COUNT(*) FROM vec_chunks"
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    pass

            return result
        finally:
            conn.close()
