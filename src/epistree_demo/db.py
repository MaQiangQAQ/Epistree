"""SQLite schema and operations for Epistree Demo.

Matches section 7 of DEMO_DESIGN.md — 7 tables.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TEXT,
    finished_at TEXT,
    real_api_calls INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    graph_bundle_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    normalized_query TEXT NOT NULL,
    query_sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    query_id TEXT NOT NULL REFERENCES queries(id),
    observed_at TEXT NOT NULL,
    from_cache INTEGER NOT NULL DEFAULT 0,
    is_expired INTEGER NOT NULL DEFAULT 0,
    search_hash_id TEXT,
    item_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_content ON sources(content_type, content_id);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    observed_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    title TEXT NOT NULL,
    content_text TEXT NOT NULL,
    author_name TEXT NOT NULL DEFAULT '',
    edit_time TEXT,
    metrics_json TEXT DEFAULT '{}',
    raw_json TEXT DEFAULT '{}',
    UNIQUE(source_id, payload_sha256)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON source_snapshots(source_id);

CREATE TABLE IF NOT EXISTS query_source_observations (
    id TEXT PRIMARY KEY,
    query_observation_id TEXT NOT NULL REFERENCES query_observations(id),
    source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
    rank INTEGER NOT NULL,
    ranking_score REAL
);

CREATE TABLE IF NOT EXISTS graph_bundles (
    id TEXT PRIMARY KEY,
    input_sha256 TEXT NOT NULL UNIQUE,
    prompt_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    bundle_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Daily call budget tracking
CREATE TABLE IF NOT EXISTS daily_budget (
    date TEXT NOT NULL,
    calls_used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date)
);
"""


class EpistreeDB:
    """Thin wrapper around sqlite3.Connection for Epistree Demo data.

    All methods are explicit SQL — no ORM.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._budget_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_schema(self) -> None:
        conn = self.connect()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── runs ────────────────────────────────────────────────────────

    def create_run(self, topic: str) -> str:
        rid = str(uuid.uuid4())
        now = _now()
        self.connect().execute(
            "INSERT INTO runs (id, topic, status, created_at) VALUES (?, ?, 'queued', ?)",
            (rid, topic, now),
        )
        self.connect().commit()
        return rid

    def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        graph_bundle_id: str | None = None,
        real_api_calls: int | None = None,
        cache_hits: int | None = None,
    ) -> None:
        now = _now()
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ValueError(f"Unknown run status: {status}")
        conn = self.connect()
        current = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if current is None:
            raise KeyError(f"Unknown run: {run_id}")
        old = current["status"]
        allowed = {
            "queued": {"queued", "running", "failed", "cancelled"},
            "running": {"running", "completed", "failed", "cancelled"},
            "completed": {"completed"}, "failed": {"failed"}, "cancelled": {"cancelled"},
        }
        if status not in allowed[old]:
            raise ValueError(f"Invalid run transition {old} -> {status}")
        finished = now if status in ("completed", "failed", "cancelled") else None
        started = now if status == "running" else None
        conn.execute(
            """UPDATE runs SET status=?, finished_at=?, error_code=COALESCE(?, error_code),
               error_message=COALESCE(?, error_message),
               graph_bundle_id=COALESCE(?, graph_bundle_id),
               real_api_calls=COALESCE(?, real_api_calls),
               cache_hits=COALESCE(?, cache_hits),
               started_at=COALESCE(?, started_at)
               WHERE id=?""",
            (status, finished, error_code, error_message, graph_bundle_id,
             real_api_calls, cache_hits, started, run_id),
        )
        conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def run_bundle_is_consistent(self, run_id: str) -> bool:
        """Check that a completed Run points to an existing graph bundle."""
        row = self.connect().execute(
            """SELECT r.status, r.graph_bundle_id, g.id AS existing_bundle_id
               FROM runs r LEFT JOIN graph_bundles g ON g.id=r.graph_bundle_id
               WHERE r.id=?""", (run_id,)
        ).fetchone()
        return bool(row and row["status"] == "completed"
                    and row["graph_bundle_id"]
                    and row["graph_bundle_id"] == row["existing_bundle_id"])

    # ── queries ─────────────────────────────────────────────────────

    def get_or_create_query(self, normalized_query: str, query_sha256: str) -> str:
        conn = self.connect()
        row = conn.execute(
            "SELECT id FROM queries WHERE query_sha256=?", (query_sha256,)
        ).fetchone()
        if row:
            return row["id"]
        qid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO queries (id, normalized_query, query_sha256, created_at) VALUES (?,?,?,?)",
            (qid, normalized_query, query_sha256, _now()),
        )
        conn.commit()
        return qid

    # ── query_observations ─────────────────────────────────────────

    def create_query_observation(
        self,
        run_id: str,
        query_id: str,
        from_cache: bool,
        is_expired: bool,
        search_hash_id: str | None,
        item_count: int,
        observed_at: datetime | None = None,
    ) -> str:
        oid = str(uuid.uuid4())
        self.connect().execute(
            """INSERT INTO query_observations
               (id, run_id, query_id, observed_at, from_cache, is_expired, search_hash_id, item_count)
               VALUES (?,?,?,?,?,?,?,?)""",
            (oid, run_id, query_id, (observed_at or datetime.now(timezone.utc)).isoformat(), int(from_cache), int(is_expired),
             search_hash_id, item_count),
        )
        self.connect().commit()
        return oid

    # ── sources & snapshots ────────────────────────────────────────

    def upsert_source(
        self, source_id: str, content_id: str, content_type: str, canonical_url: str
    ) -> None:
        now = _now()
        conn = self.connect()
        conn.execute(
            """INSERT INTO sources (id, content_id, content_type, canonical_url, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
            (source_id, content_id, content_type, canonical_url, now, now),
        )
        conn.commit()

    def insert_snapshot(self, snapshot_id: str, source_id: str, payload_sha256: str,
                        title: str, content_text: str, author_name: str,
                        edit_time: str | None, metrics_json: str,
                        raw_json: str, observed_at: datetime | None = None) -> str:
        """Insert a snapshot, returning the snapshot ID (new or existing)."""
        conn = self.connect()
        try:
            conn.execute(
                """INSERT INTO source_snapshots
                   (id, source_id, observed_at, payload_sha256, title, content_text,
                    author_name, edit_time, metrics_json, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, source_id, (observed_at or datetime.now(timezone.utc)).isoformat(), payload_sha256, title, content_text,
                 author_name, edit_time, metrics_json, raw_json),
            )
            conn.commit()
            return snapshot_id
        except sqlite3.IntegrityError:
            # Duplicate (source_id, payload_sha256) — return existing ID
            conn.rollback()
            row = conn.execute(
                "SELECT id FROM source_snapshots WHERE source_id=? AND payload_sha256=?",
                (source_id, payload_sha256),
            ).fetchone()
            return row["id"] if row else snapshot_id

    # ── query_source_observations ──────────────────────────────────

    def link_source_to_query_observation(
        self, query_observation_id: str, source_snapshot_id: str,
                        rank: int, ranking_score: float | None,
    ) -> None:
        oid = str(uuid.uuid4())
        self.connect().execute(
            """INSERT INTO query_source_observations
               (id, query_observation_id, source_snapshot_id, rank, ranking_score)
               VALUES (?,?,?,?,?)""",
            (oid, query_observation_id, source_snapshot_id, rank, ranking_score),
        )
        self.connect().commit()

    def persist_search_observation(
        self, run_id: str, query_id: str, outcome: object, items: list[object]
    ) -> None:
        """Persist one response and all of its source rows atomically.

        The adapter object is intentionally duck-typed to keep this database
        layer independent from the HTTP client.
        """
        conn = self.connect()
        observed_at = outcome.observed_at.isoformat()
        raw_response = outcome.response.raw_json or {}
        raw_items = (raw_response.get("Data") or {}).get("Items", [])
        raw_item_map = {
            (str(raw.get("ContentType", "unknown")).lower(), str(raw.get("ContentID", ""))): raw
            for raw in raw_items
            if isinstance(raw, dict)
        }
        try:
            conn.execute("BEGIN")
            obs_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO query_observations
                   (id, run_id, query_id, observed_at, from_cache, is_expired, search_hash_id, item_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (obs_id, run_id, query_id, observed_at, int(outcome.cache_state != "miss"),
                 int(outcome.cache_state == "stale"), outcome.response.search_hash_id, len(items)),
            )
            for rank, item in enumerate(items):
                now = _now()
                conn.execute(
                    """INSERT INTO sources(id,content_id,content_type,canonical_url,first_seen_at,last_seen_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                    (item.source_id, item.content_id, item.content_type, str(item.url), now, now),
                )
                payload = json.dumps({
                    "title": item.title, "content_text": item.content_text,
                    "author_name": item.author_name,
                    "edit_time": item.edit_time.isoformat() if item.edit_time else None,
                }, ensure_ascii=False, sort_keys=True)
                payload_sha = hashlib.sha256(payload.encode()).hexdigest()
                row = conn.execute(
                    "SELECT id FROM source_snapshots WHERE source_id=? AND payload_sha256=?",
                    (item.source_id, payload_sha),
                ).fetchone()
                snap_id = row["id"] if row else str(uuid.uuid4())
                if row is None:
                    conn.execute(
                        """INSERT INTO source_snapshots
                           (id,source_id,observed_at,payload_sha256,title,content_text,author_name,edit_time,metrics_json,raw_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (snap_id, item.source_id, observed_at, payload_sha, item.title, item.content_text,
                         item.author_name, item.edit_time.isoformat() if item.edit_time else None,
                         json.dumps({"vote_up_count": item.vote_up_count,
                         "comment_count": item.comment_count, "authority_level": item.authority_level}),
                         json.dumps(
                             raw_item_map.get((item.content_type, item.content_id), {}),
                             ensure_ascii=False,
                         )),
                    )
                conn.execute(
                    "INSERT INTO query_source_observations(id,query_observation_id,source_snapshot_id,rank,ranking_score) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), obs_id, snap_id, rank, item.ranking_score),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── graph_bundles ──────────────────────────────────────────────

    def get_bundle_by_hash(self, input_sha256: str) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM graph_bundles WHERE input_sha256=?", (input_sha256,)
        ).fetchone()
        return dict(row) if row else None

    def get_bundle_by_id(self, bundle_id: str) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM graph_bundles WHERE id=?", (bundle_id,)
        ).fetchone()
        return dict(row) if row else None

    def save_bundle(self, bundle_id: str, input_sha256: str,
                    prompt_version: str, model_name: str,
                    bundle_json: str) -> None:
        try:
            self.connect().execute(
                """INSERT INTO graph_bundles
                   (id, input_sha256, prompt_version, model_name, bundle_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (bundle_id, input_sha256, prompt_version, model_name, bundle_json, _now()),
            )
            self.connect().commit()
        except sqlite3.IntegrityError:
            row = self.connect().execute(
                "SELECT id FROM graph_bundles WHERE input_sha256=?", (input_sha256,)
            ).fetchone()
            return row["id"] if row else bundle_id
        return bundle_id

    def reserve_daily_call(self, date: str, limit: int) -> bool:
        """Atomically reserve one real search attempt under the local limit."""
        with self._budget_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT calls_used FROM daily_budget WHERE date=?", (date,)
                ).fetchone()
                used = int(row["calls_used"]) if row else 0
                if used >= limit:
                    conn.rollback()
                    return False
                conn.execute(
                    "INSERT INTO daily_budget(date,calls_used) VALUES(?,1) "
                    "ON CONFLICT(date) DO UPDATE SET calls_used=calls_used+1", (date,)
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    # ── daily budget ───────────────────────────────────────────────

    def get_daily_calls(self, date: str) -> int:
        row = self.connect().execute(
            "SELECT calls_used FROM daily_budget WHERE date=?", (date,)
        ).fetchone()
        return row["calls_used"] if row else 0

    def increment_daily_calls(self, date: str) -> int:
        conn = self.connect()
        conn.execute(
            "INSERT INTO daily_budget (date, calls_used) VALUES (?, 1) "
            "ON CONFLICT(date) DO UPDATE SET calls_used = calls_used + 1",
            (date,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT calls_used FROM daily_budget WHERE date=?", (date,)
        ).fetchone()
        return row["calls_used"] if row else 0

    # ── misc ───────────────────────────────────────────────────────

    def count_used_sources(self) -> dict[str, int]:
        """Return count of items by content_type to validate test fixtures."""
        rows = self.connect().execute(
            "SELECT content_type, COUNT(*) as cnt FROM sources GROUP BY content_type"
        ).fetchall()
        return {r["content_type"]: r["cnt"] for r in rows}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
