"""SQLite storage for what happened: answers, feedback, and what each one cost.

The split this file sits on one side of: **SQLite holds what happened, Markdown
holds what you know.** Practice runs are an append-only log - you want to see
whether the same question goes better next month - so they belong in a database.
Stories and the CV are material you edit and review, so they stay as files you
can diff.

stdlib sqlite3, one file, no ORM and no migrations. The schema is small enough to
read in one screen, and a practice log that loses a row is not a crisis.

Feedback is stored as JSON rather than shredded across tables. It is read back
whole, never queried field by field, and keeping it as one blob means the schema
does not have to change every time the Feedback model gains a field.

Story additions proposed by a run are pending until a row in `patch_decisions`
records that they were accepted or dismissed. The proposal itself stays inside
`feedback_json`; the decision is the only new fact.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "runtime" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    question_id  TEXT NOT NULL,
    created_at   REAL NOT NULL,
    duration_s   REAL,
    transcript   TEXT,
    metrics_json TEXT,
    feedback_json TEXT,
    cost_usd     REAL DEFAULT 0,
    audio_path   TEXT
);
CREATE INDEX IF NOT EXISTS runs_by_question ON runs (question_id, created_at DESC);
CREATE TABLE IF NOT EXISTS patch_decisions (
    run_id     TEXT PRIMARY KEY,
    decision   TEXT NOT NULL,
    decided_at REAL NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_run(run: Any, path: Path | None = None) -> None:
    """Persist a finished run. Never raises into the pipeline.

    A practice session that completed successfully must not be reported as
    failed because writing the log row did not work.
    """
    try:
        with connect(path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, question_id, created_at, "
                "duration_s, transcript, metrics_json, feedback_json, cost_usd, "
                "audio_path) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.question_id,
                    run.started_at,
                    run.transcript.duration_s if run.transcript else None,
                    run.transcript.text if run.transcript else None,
                    json.dumps(run.metrics.model_dump()) if run.metrics else None,
                    json.dumps(run.feedback.model_dump()) if run.feedback else None,
                    run.cost_usd,
                    str(run.audio_path),
                ),
            )
    except sqlite3.Error as exc:
        print(f"[db] could not save run {run.id}: {exc}")


def history(question_id: str | None = None, limit: int = 20,
            path: Path | None = None) -> list[dict]:
    """Past answers, newest first. Filtered to one question when given one,
    which is how you see whether the same answer is improving."""
    sql = ("SELECT id, question_id, created_at, duration_s, transcript, "
           "metrics_json, feedback_json, cost_usd FROM runs")
    params: tuple = ()
    if question_id:
        sql += " WHERE question_id = ?"
        params = (question_id,)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params += (limit,)

    with connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": r["id"],
            "question_id": r["question_id"],
            "created_at": r["created_at"],
            "duration_s": r["duration_s"],
            "transcript": r["transcript"],
            "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else None,
            "feedback": json.loads(r["feedback_json"]) if r["feedback_json"] else None,
            "cost_usd": r["cost_usd"],
        }
        for r in rows
    ]


def latest_feedback(question_id: str, path: Path | None = None) -> dict | None:
    """The most recent feedback for one question, read raw.

    Raw rather than validated: runs stored before a schema change must still
    serve as the previous attempt.
    """
    rows = history(question_id, 1, path)
    return rows[0]["feedback"] if rows else None


def pending_patches(path: Path | None = None) -> list[dict]:
    """Story additions from past runs that nobody has accepted or dismissed yet,
    newest first."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT r.id, r.question_id, r.created_at, r.feedback_json FROM runs r "
            "LEFT JOIN patch_decisions d ON d.run_id = r.id "
            "WHERE d.run_id IS NULL AND r.feedback_json IS NOT NULL "
            "ORDER BY r.created_at DESC"
        ).fetchall()

    pending = []
    for r in rows:
        patch = json.loads(r["feedback_json"]).get("story_patch")
        if patch:
            pending.append({"run_id": r["id"], "question_id": r["question_id"],
                            "created_at": r["created_at"], "patch": patch})
    return pending


def pending_patch(run_id: str, path: Path | None = None) -> dict | None:
    return next((p for p in pending_patches(path) if p["run_id"] == run_id), None)


def record_decision(run_id: str, decision: str, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO patch_decisions (run_id, decision, decided_at) "
            "VALUES (?,?,?)",
            (run_id, decision, time.time()),
        )


def totals(path: Path | None = None) -> dict:
    """Answer count and total spend, for the footer."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS runs, COALESCE(SUM(cost_usd), 0) AS cost FROM runs"
        ).fetchone()
    return {"runs": row["runs"], "cost_usd": round(row["cost"], 4)}
