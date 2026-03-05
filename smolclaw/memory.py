"""Namespaced memory system — shared SQLite DB with per-agent scoping."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger("smolclaw")

__all__ = ["Memory"]


class Memory:
    """Agent-namespaced memory backed by SQLite.

    All agents share one memory.db. Each entry is tagged with an agent name.
    Agents query their own namespace by default, with optional cross-agent search.
    """

    def __init__(self, db_path: Path, agent: str = "shared"):
        """Initialize memory for an agent, creating tables if needed.

        Args:
            db_path: Path to the shared SQLite database file.
            agent: Agent name used to namespace all stored data.
        """
        self.db_path = db_path
        self.agent = agent
        self._ensure_schema()

    def __repr__(self) -> str:
        return f"Memory(agent={self.agent!r}, db={self.db_path})"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Create tables, indexes, and FTS5 full-text search. Enables WAL mode."""
        conn = self._connect()
        try:
            # WAL mode allows concurrent readers with one writer — prevents
            # "database is locked" errors when multiple agents share one DB.
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

    @staticmethod
    def _fts5_escape(query: str) -> str:
        """Escape a query for FTS5 MATCH — quote each token as a literal."""
        special = set('"*()^:+')
        cleaned = "".join(c if c not in special else " " for c in query)
        words = cleaned.split()
        if not words:
            return ""
        return " ".join(f'"{w}"' for w in words)

    def add_fact(self, content: str, category: str = "general", source: str = "manual") -> int:
        """Add a fact to this agent's namespace."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT INTO facts (agent, content, category, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.agent, content, category, source, datetime.now().isoformat()),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def search_facts(self, query: str, limit: int = 10, cross_agent: bool = False) -> list[dict]:
        """Search facts using FTS5 full-text search with BM25 ranking.

        Falls back to LIKE search if FTS5 query fails.
        """
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

    def add_chunk(
        self,
        user_text: str,
        assistant_text: str = "",
        session_id: str = "",
    ) -> int:
        """Store a conversation chunk in this agent's namespace."""
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
            conn.commit()
            return cursor.lastrowid
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
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def clear(self) -> dict[str, int]:
        """Clear all facts and chunks for this agent. Returns counts of deleted rows."""
        conn = self._connect()
        try:
            facts_deleted = conn.execute(
                "DELETE FROM facts WHERE agent = ?", (self.agent,)
            ).rowcount
            chunks_deleted = conn.execute(
                "DELETE FROM chunks WHERE agent = ?", (self.agent,)
            ).rowcount
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
            return {
                "agent": self.agent,
                "facts": facts_count,
                "chunks": chunks_count,
                "total_facts": total_facts,
                "total_chunks": total_chunks,
            }
        finally:
            conn.close()
