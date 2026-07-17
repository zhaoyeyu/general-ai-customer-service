from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

from .models import PublicSettings, SettingsUpdate


DEFAULTS = PublicSettings().model_dump(exclude={"has_api_key"})


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "customer_service.db"
        self.key_path = data_dir / ".master.key"
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    route TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    retrieval_score REAL NOT NULL DEFAULT 0,
                    sources_count INTEGER NOT NULL DEFAULT 0,
                    input_chars INTEGER NOT NULL DEFAULT 0,
                    output_chars INTEGER NOT NULL DEFAULT 0,
                    usage_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_traces_created ON traces(created_at DESC);
                CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_handoffs_status ON handoffs(status, created_at DESC);
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trace_id)
                );
                """
            )

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(self.key_path.read_bytes())

    def get_settings(self) -> PublicSettings:
        values = dict(DEFAULTS)
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings WHERE key != 'api_key'").fetchall()
            for row in rows:
                if row["key"] in values:
                    values[row["key"]] = json.loads(row["value"])
            has_stored = conn.execute("SELECT 1 FROM settings WHERE key = 'api_key'").fetchone() is not None
        has_env = bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))
        return PublicSettings(**values, has_api_key=has_stored or has_env)

    def save_settings(self, update: SettingsUpdate) -> PublicSettings:
        public = update.model_dump(exclude={"api_key", "clear_api_key"})
        with self.connect() as conn:
            for key, value in public.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            if update.clear_api_key:
                conn.execute("DELETE FROM settings WHERE key = 'api_key'")
            elif update.api_key and update.api_key.strip():
                encrypted = self._fernet().encrypt(update.api_key.strip().encode()).decode()
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES ('api_key', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (encrypted,),
                )
        return self.get_settings()

    def get_api_key(self) -> str | None:
        env_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        if env_key:
            return env_key
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'api_key'").fetchone()
        if not row:
            return None
        try:
            return self._fernet().decrypt(row["value"].encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("API Key 无法解密，请在设置页重新录入") from exc

    def add_document(self, filename: str, content_type: str, text: str, chunks: list[str]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO documents(filename, content_type, char_count, chunk_count) VALUES (?, ?, ?, ?)",
                (filename, content_type, len(text), len(chunks)),
            )
            document_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO chunks(document_id, chunk_index, content) VALUES (?, ?, ?)",
                [(document_id, index, content) for index, content in enumerate(chunks)],
            )
        return document_id

    def list_documents(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, filename, content_type, char_count, chunk_count, created_at "
                "FROM documents ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_document(self, document_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0

    def all_chunks(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT chunks.id, chunks.document_id, chunks.chunk_index, chunks.content, documents.filename "
                "FROM chunks JOIN documents ON documents.id = chunks.document_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS documents, COALESCE(SUM(chunk_count), 0) AS chunks, "
                "COALESCE(SUM(char_count), 0) AS characters FROM documents"
            ).fetchone()
        return dict(row)

    def ensure_conversation(self, conversation_id: str | None = None) -> str:
        candidate = conversation_id or uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO conversations(id) VALUES (?) ON CONFLICT(id) DO NOTHING",
                (candidate,),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (candidate,),
            )
        return candidate

    def add_message(self, conversation_id: str, role: str, content: str, metadata: dict | None = None) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages(conversation_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )
        return int(cursor.lastrowid)

    def get_messages(self, conversation_id: str, limit: int = 12) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT role, content, metadata_json, created_at FROM ("
                "SELECT id, role, content, metadata_json, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (conversation_id, limit),
            ).fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_trace(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        route: str,
        status: str,
        model: str = "",
        latency_ms: int = 0,
        retrieval_score: float = 0,
        sources_count: int = 0,
        input_chars: int = 0,
        output_chars: int = 0,
        usage: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO traces(id, conversation_id, route, status, model, latency_ms, retrieval_score, "
                "sources_count, input_chars, output_chars, usage_json, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trace_id,
                    conversation_id,
                    route,
                    status,
                    model,
                    latency_ms,
                    retrieval_score,
                    sources_count,
                    input_chars,
                    output_chars,
                    json.dumps(usage, ensure_ascii=False) if usage else None,
                    error,
                ),
            )

    def add_trace_event(self, trace_id: str, stage: str, duration_ms: int = 0, metadata: dict | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO trace_events(trace_id, stage, duration_ms, metadata_json) VALUES (?, ?, ?, ?)",
                (trace_id, stage, duration_ms, json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def create_handoff(self, conversation_id: str, reason: str, summary: str) -> str:
        handoff_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO handoffs(id, conversation_id, reason, summary) VALUES (?, ?, ?, ?)",
                (handoff_id, conversation_id, reason, summary),
            )
            conn.execute("UPDATE conversations SET status = 'handoff' WHERE id = ?", (conversation_id,))
        return handoff_id

    def list_handoffs(self, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, conversation_id, reason, summary, status, created_at, resolved_at "
                "FROM handoffs ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, "
                "created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_handoff(self, handoff_id: str, status: str) -> bool:
        resolved_at = "CURRENT_TIMESTAMP" if status == "resolved" else "NULL"
        with self.connect() as conn:
            cursor = conn.execute(
                f"UPDATE handoffs SET status = ?, resolved_at = {resolved_at} WHERE id = ?",
                (status, handoff_id),
            )
        return cursor.rowcount > 0

    def add_feedback(self, trace_id: str, rating: int, comment: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO feedback(trace_id, rating, comment) VALUES (?, ?, ?) "
                "ON CONFLICT(trace_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment",
                (trace_id, rating, comment),
            )

    def list_traces(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT traces.id, traces.conversation_id, traces.route, traces.status, traces.model, "
                "traces.latency_ms, traces.retrieval_score, traces.sources_count, traces.input_chars, "
                "traces.output_chars, traces.usage_json, traces.error, traces.created_at, feedback.rating "
                "FROM traces LEFT JOIN feedback ON feedback.trace_id = traces.id "
                "ORDER BY traces.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["usage"] = json.loads(item.pop("usage_json")) if item["usage_json"] else None
            results.append(item)
        return results

    def metrics(self) -> dict:
        with self.connect() as conn:
            trace = conn.execute(
                "SELECT COUNT(*) AS runs, "
                "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, "
                "COALESCE(AVG(retrieval_score), 0) AS avg_retrieval_score, "
                "COALESCE(SUM(CASE WHEN route = 'human_handoff' THEN 1 ELSE 0 END), 0) AS handoffs, "
                "COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) AS errors "
                "FROM traces"
            ).fetchone()
            feedback = conn.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS positive "
                "FROM feedback"
            ).fetchone()
            pending = conn.execute("SELECT COUNT(*) AS count FROM handoffs WHERE status != 'resolved'").fetchone()
        result = dict(trace)
        result["feedback_total"] = feedback["total"] or 0
        result["feedback_positive"] = feedback["positive"] or 0
        result["pending_handoffs"] = pending["count"] or 0
        return result
