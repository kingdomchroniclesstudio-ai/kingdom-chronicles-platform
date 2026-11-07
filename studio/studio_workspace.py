from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


PROJECT_STATUSES = {"DEVELOPMENT", "PRE_PRODUCTION", "PRODUCTION", "POST_PRODUCTION", "COMPLETED", "ON_HOLD"}
SCENE_STATUSES = {"PLANNED", "IN_PROGRESS", "READY", "COMPLETE", "ON_HOLD"}
SHOT_STATUSES = {"PLANNED", "READY", "GENERATED", "IN_REVIEW", "APPROVED", "REJECTED", "ON_HOLD"}
TEST_RESULTS = {"PLANNED", "PASSED", "FAILED", "NEEDS_REVIEW"}
ASSET_CATEGORIES = {"CHARACTER", "LOCATION", "PROP", "WARDROBE", "REFERENCE", "SOUND", "OTHER"}


class StudioWorkspace:
    """Small, authenticated, SQLite-backed production-planning workspace.

    This database stores project metadata and test records only. It does not
    submit GPU jobs, store generated videos, or alter the controller's take
    approval state. It uses the controller's resolved data root so a Render
    persistent disk can protect records once HRF_DATA_DIR is configured.
    """

    def __init__(self, data_root: Path | str) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_root / "studio_workspace.sqlite3"
        self._initialize()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=8.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=8000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_projects (
                    project_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    film_type TEXT NOT NULL DEFAULT 'FEATURE_FILM',
                    status TEXT NOT NULL DEFAULT 'DEVELOPMENT',
                    synopsis TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_scenes (
                    scene_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES studio_projects(project_id) ON DELETE CASCADE,
                    scene_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PLANNED',
                    location TEXT NOT NULL DEFAULT '',
                    synopsis TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, scene_number)
                );
                CREATE TABLE IF NOT EXISTS studio_shots (
                    shot_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES studio_projects(project_id) ON DELETE CASCADE,
                    scene_id TEXT NOT NULL REFERENCES studio_scenes(scene_id) ON DELETE CASCADE,
                    shot_code TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'PLANNED',
                    priority TEXT NOT NULL DEFAULT 'NORMAL',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scene_id, shot_code)
                );
                CREATE TABLE IF NOT EXISTS studio_tests (
                    test_id TEXT PRIMARY KEY,
                    project_id TEXT REFERENCES studio_projects(project_id) ON DELETE SET NULL,
                    scene_id TEXT REFERENCES studio_scenes(scene_id) ON DELETE SET NULL,
                    shot_code TEXT NOT NULL DEFAULT '',
                    test_name TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL DEFAULT '',
                    workflow TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '',
                    seed TEXT NOT NULL DEFAULT '',
                    resolution TEXT NOT NULL DEFAULT '',
                    frame_rate INTEGER,
                    duration_seconds REAL,
                    gpu_minutes REAL NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    comparison_group TEXT NOT NULL DEFAULT '',
                    result_status TEXT NOT NULL DEFAULT 'PLANNED',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_assets (
                    asset_id TEXT PRIMARY KEY,
                    project_id TEXT REFERENCES studio_projects(project_id) ON DELETE SET NULL,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    reference_code TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    continuity_notes TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_reviews (
                    review_id TEXT PRIMARY KEY,
                    take_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    decision TEXT NOT NULL DEFAULT 'NOTE',
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studio_scenes_project ON studio_scenes(project_id, scene_number);
                CREATE INDEX IF NOT EXISTS idx_studio_shots_scene ON studio_shots(scene_id, shot_code);
                CREATE INDEX IF NOT EXISTS idx_studio_tests_project ON studio_tests(project_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_studio_assets_project ON studio_assets(project_id, category);
                CREATE INDEX IF NOT EXISTS idx_studio_reviews_take ON studio_reviews(take_id, created_at);
            """)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _text(value: Any, field: str, maximum: int, required: bool = False) -> str:
        if value is None:
            value = ""
        if not isinstance(value, (str, int, float)):
            raise ValueError(f"{field} must be text")
        result = str(value).strip()
        if required and not result:
            raise ValueError(f"{field} is required")
        if len(result) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return result

    @staticmethod
    def _enum(value: Any, field: str, allowed: set[str], default: str) -> str:
        result = str(value or default).strip().upper()
        if result not in allowed:
            raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
        return result

    @staticmethod
    def _number(value: Any, field: str, minimum: float, maximum: float, optional: bool = False) -> float | None:
        if value in (None, "") and optional:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number") from exc
        if result < minimum or result > maximum:
            raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
        return result

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

    def storage_status(self) -> dict[str, Any]:
        configured = bool(os.environ.get("HRF_DATA_DIR", "").strip())
        return {
            "database": "studio_workspace.sqlite3",
            "data_root_configured": configured,
            "status": "persistent-root-configured" if configured else "persistent-root-pending",
            "note": "HRF_DATA_DIR is configured." if configured else "Set HRF_DATA_DIR to the mounted Render disk before relying on restart-safe records.",
        }

    def create_project(self, body: dict[str, Any]) -> dict[str, Any]:
        title = self._text(body.get("title"), "title", 120, True)
        film_type = self._text(body.get("film_type") or "FEATURE_FILM", "film_type", 40, True).upper()
        status = self._enum(body.get("status"), "status", PROJECT_STATUSES, "DEVELOPMENT")
        synopsis = self._text(body.get("synopsis"), "synopsis", 2000)
        now = self._now()
        item = {"project_id": self._id("HRF"), "title": title, "film_type": film_type, "status": status, "synopsis": synopsis, "created_at": now, "updated_at": now}
        with self._db() as db:
            db.execute("INSERT INTO studio_projects(project_id,title,film_type,status,synopsis,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (item["project_id"], title, film_type, status, synopsis, now, now))
        return item

    def list_projects(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("""
                SELECT p.*,
                  (SELECT COUNT(*) FROM studio_scenes s WHERE s.project_id=p.project_id) AS scene_count,
                  (SELECT COUNT(*) FROM studio_shots h WHERE h.project_id=p.project_id) AS shot_count,
                  (SELECT COUNT(*) FROM studio_shots h WHERE h.project_id=p.project_id AND h.status='APPROVED') AS approved_shot_count,
                  (SELECT COUNT(*) FROM studio_tests t WHERE t.project_id=p.project_id) AS test_count,
                  (SELECT COUNT(*) FROM studio_assets a WHERE a.project_id=p.project_id) AS asset_count
                FROM studio_projects p ORDER BY p.updated_at DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def create_scene(self, body: dict[str, Any]) -> dict[str, Any]:
        project_id = self._text(body.get("project_id"), "project_id", 64, True)
        try:
            scene_number = int(body.get("scene_number"))
        except (TypeError, ValueError) as exc:
            raise ValueError("scene_number must be a whole number") from exc
        if scene_number < 1 or scene_number > 9999:
            raise ValueError("scene_number must be between 1 and 9999")
        title = self._text(body.get("title"), "title", 120, True)
        status = self._enum(body.get("status"), "status", SCENE_STATUSES, "PLANNED")
        location = self._text(body.get("location"), "location", 160)
        synopsis = self._text(body.get("synopsis"), "synopsis", 2000)
        now = self._now()
        item = {"scene_id": self._id("SCN"), "project_id": project_id, "scene_number": scene_number, "title": title, "status": status, "location": location, "synopsis": synopsis, "created_at": now, "updated_at": now}
        with self._db() as db:
            if not db.execute("SELECT 1 FROM studio_projects WHERE project_id=?", (project_id,)).fetchone():
                raise ValueError("project_id does not exist")
            db.execute("INSERT INTO studio_scenes(scene_id,project_id,scene_number,title,status,location,synopsis,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (item["scene_id"], project_id, scene_number, title, status, location, synopsis, now, now))
        return item

    def list_scenes(self, project_id: str) -> list[dict[str, Any]]:
        project_id = self._text(project_id, "project_id", 64, True)
        with self._db() as db:
            rows = db.execute("""
                SELECT s.*,(SELECT COUNT(*) FROM studio_shots h WHERE h.scene_id=s.scene_id) AS shot_count
                FROM studio_scenes s WHERE s.project_id=? ORDER BY s.scene_number
            """, (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_shot(self, body: dict[str, Any]) -> dict[str, Any]:
        project_id = self._text(body.get("project_id"), "project_id", 64, True)
        scene_id = self._text(body.get("scene_id"), "scene_id", 64, True)
        shot_code = self._text(body.get("shot_code"), "shot_code", 64, True).upper()
        description = self._text(body.get("description"), "description", 2000)
        status = self._enum(body.get("status"), "status", SHOT_STATUSES, "PLANNED")
        priority = self._enum(body.get("priority"), "priority", {"LOW", "NORMAL", "HIGH"}, "NORMAL")
        now = self._now()
        item = {"shot_id": self._id("SHT"), "project_id": project_id, "scene_id": scene_id, "shot_code": shot_code, "description": description, "status": status, "priority": priority, "created_at": now, "updated_at": now}
        with self._db() as db:
            row = db.execute("SELECT project_id FROM studio_scenes WHERE scene_id=?", (scene_id,)).fetchone()
            if not row or row["project_id"] != project_id:
                raise ValueError("scene_id does not belong to project_id")
            db.execute("INSERT INTO studio_shots(shot_id,project_id,scene_id,shot_code,description,status,priority,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (item["shot_id"], project_id, scene_id, shot_code, description, status, priority, now, now))
        return item

    def list_shots(self, project_id: str = "", scene_id: str = "") -> list[dict[str, Any]]:
        clauses, values = [], []
        if project_id:
            clauses.append("project_id=?")
            values.append(self._text(project_id, "project_id", 64, True))
        if scene_id:
            clauses.append("scene_id=?")
            values.append(self._text(scene_id, "scene_id", 64, True))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._db() as db:
            rows = db.execute("SELECT * FROM studio_shots" + where + " ORDER BY created_at DESC LIMIT 300", values).fetchall()
        return [dict(row) for row in rows]

    def create_test(self, body: dict[str, Any]) -> dict[str, Any]:
        project_id = self._text(body.get("project_id"), "project_id", 64)
        scene_id = self._text(body.get("scene_id"), "scene_id", 64)
        if project_id:
            with self._db() as db:
                if not db.execute("SELECT 1 FROM studio_projects WHERE project_id=?", (project_id,)).fetchone():
                    raise ValueError("project_id does not exist")
                if scene_id and not db.execute("SELECT 1 FROM studio_scenes WHERE scene_id=? AND project_id=?", (scene_id, project_id)).fetchone():
                    raise ValueError("scene_id does not belong to project_id")
        test_name = self._text(body.get("test_name"), "test_name", 120, True)
        purpose = self._text(body.get("purpose"), "purpose", 300)
        model_name = self._text(body.get("model_name"), "model_name", 120)
        workflow = self._text(body.get("workflow"), "workflow", 120)
        prompt = self._text(body.get("prompt"), "prompt", 5000)
        seed = self._text(body.get("seed"), "seed", 40)
        resolution = self._text(body.get("resolution"), "resolution", 40)
        frame_rate_raw = self._number(body.get("frame_rate"), "frame_rate", 1, 240, optional=True)
        duration = self._number(body.get("duration_seconds"), "duration_seconds", 0, 3600, optional=True)
        gpu_minutes = self._number(body.get("gpu_minutes", 0), "gpu_minutes", 0, 100000) or 0
        cost_usd = self._number(body.get("cost_usd", 0), "cost_usd", 0, 1000000) or 0
        comparison_group = self._text(body.get("comparison_group"), "comparison_group", 100)
        result_status = self._enum(body.get("result_status"), "result_status", TEST_RESULTS, "PLANNED")
        notes = self._text(body.get("notes"), "notes", 3000)
        now = self._now()
        item = {"test_id": self._id("TST"), "project_id": project_id or None, "scene_id": scene_id or None, "shot_code": self._text(body.get("shot_code"), "shot_code", 64), "test_name": test_name, "purpose": purpose, "model_name": model_name, "workflow": workflow, "prompt": prompt, "seed": seed, "resolution": resolution, "frame_rate": int(frame_rate_raw) if frame_rate_raw is not None and frame_rate_raw.is_integer() else frame_rate_raw, "duration_seconds": duration, "gpu_minutes": gpu_minutes, "cost_usd": cost_usd, "comparison_group": comparison_group, "result_status": result_status, "notes": notes, "created_at": now, "updated_at": now}
        with self._db() as db:
            db.execute("""INSERT INTO studio_tests(test_id,project_id,scene_id,shot_code,test_name,purpose,model_name,workflow,prompt,seed,resolution,frame_rate,duration_seconds,gpu_minutes,cost_usd,comparison_group,result_status,notes,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(item[key] for key in ("test_id","project_id","scene_id","shot_code","test_name","purpose","model_name","workflow","prompt","seed","resolution","frame_rate","duration_seconds","gpu_minutes","cost_usd","comparison_group","result_status","notes","created_at","updated_at")))
        return item

    def list_tests(self, project_id: str = "") -> list[dict[str, Any]]:
        with self._db() as db:
            if project_id:
                rows = db.execute("SELECT * FROM studio_tests WHERE project_id=? ORDER BY created_at DESC LIMIT 300", (project_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM studio_tests ORDER BY created_at DESC LIMIT 300").fetchall()
        return [dict(row) for row in rows]

    def create_asset(self, body: dict[str, Any]) -> dict[str, Any]:
        project_id = self._text(body.get("project_id"), "project_id", 64)
        category = self._enum(body.get("category"), "category", ASSET_CATEGORIES, "REFERENCE")
        name = self._text(body.get("name"), "name", 120, True)
        reference_code = self._text(body.get("reference_code"), "reference_code", 80)
        description = self._text(body.get("description"), "description", 2000)
        continuity_notes = self._text(body.get("continuity_notes"), "continuity_notes", 2000)
        raw_tags = body.get("tags", [])
        if isinstance(raw_tags, str):
            tags = [v.strip() for v in raw_tags.split(",") if v.strip()]
        elif isinstance(raw_tags, list):
            tags = [self._text(v, "tag", 40, True) for v in raw_tags[:20]]
        else:
            raise ValueError("tags must be a comma-separated string or array")
        if len(tags) > 20:
            raise ValueError("no more than 20 tags are allowed")
        now = self._now()
        item = {"asset_id": self._id("AST"), "project_id": project_id or None, "category": category, "name": name, "reference_code": reference_code, "description": description, "continuity_notes": continuity_notes, "tags": tags, "created_at": now, "updated_at": now}
        with self._db() as db:
            if project_id and not db.execute("SELECT 1 FROM studio_projects WHERE project_id=?", (project_id,)).fetchone():
                raise ValueError("project_id does not exist")
            db.execute("INSERT INTO studio_assets(asset_id,project_id,category,name,reference_code,description,continuity_notes,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (item["asset_id"], item["project_id"], category, name, reference_code, description, continuity_notes, json.dumps(tags), now, now))
        return item

    def list_assets(self, project_id: str = "", category: str = "") -> list[dict[str, Any]]:
        clauses, values = [], []
        if project_id:
            clauses.append("project_id=?")
            values.append(self._text(project_id, "project_id", 64, True))
        if category:
            clauses.append("category=?")
            values.append(self._enum(category, "category", ASSET_CATEGORIES, "REFERENCE"))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._db() as db:
            rows = db.execute("SELECT * FROM studio_assets" + where + " ORDER BY updated_at DESC LIMIT 300", values).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item.get("tags") or "[]")
            output.append(item)
        return output

    def create_review(self, body: dict[str, Any]) -> dict[str, Any]:
        take_id = self._text(body.get("take_id"), "take_id", 120, True)
        try:
            rating = int(body.get("rating"))
        except (TypeError, ValueError) as exc:
            raise ValueError("rating must be an integer from 1 to 5") from exc
        if rating < 1 or rating > 5:
            raise ValueError("rating must be an integer from 1 to 5")
        decision = self._enum(body.get("decision"), "decision", {"NOTE", "REVISION_REQUEST"}, "NOTE")
        note = self._text(body.get("note"), "note", 3000, True)
        item = {"review_id": self._id("REV"), "take_id": take_id, "rating": rating, "decision": decision, "note": note, "created_at": self._now()}
        with self._db() as db:
            db.execute("INSERT INTO studio_reviews(review_id,take_id,rating,decision,note,created_at) VALUES(?,?,?,?,?,?)",
                       (item["review_id"], take_id, rating, decision, note, item["created_at"]))
        return item

    def list_reviews(self, take_id: str = "") -> list[dict[str, Any]]:
        with self._db() as db:
            if take_id:
                rows = db.execute("SELECT * FROM studio_reviews WHERE take_id=? ORDER BY created_at DESC LIMIT 300", (take_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM studio_reviews ORDER BY created_at DESC LIMIT 300").fetchall()
        return [dict(row) for row in rows]

    def update_status(self, resource: str, resource_id: str, status: str) -> dict[str, Any]:
        tables = {
            "project": ("studio_projects", "project_id", PROJECT_STATUSES),
            "scene": ("studio_scenes", "scene_id", SCENE_STATUSES),
            "shot": ("studio_shots", "shot_id", SHOT_STATUSES),
            "test": ("studio_tests", "test_id", TEST_RESULTS),
        }
        if resource not in tables:
            raise ValueError("unsupported resource type")
        table, key, allowed = tables[resource]
        status = self._enum(status, "status", allowed, "")
        resource_id = self._text(resource_id, "id", 80, True)
        now = self._now()
        with self._db() as db:
            cursor = db.execute(f"UPDATE {table} SET status=?, updated_at=? WHERE {key}=?", (status, now, resource_id))
            if cursor.rowcount != 1:
                raise ValueError(f"{resource} was not found")
            row = db.execute(f"SELECT * FROM {table} WHERE {key}=?", (resource_id,)).fetchone()
        return dict(row)

    def overview(self) -> dict[str, Any]:
        with self._db() as db:
            def count(table: str) -> int:
                return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            totals = {key: count(table) for key, table in {
                "projects": "studio_projects", "scenes": "studio_scenes", "shots": "studio_shots",
                "tests": "studio_tests", "assets": "studio_assets", "reviews": "studio_reviews"
            }.items()}
            passed = int(db.execute("SELECT COUNT(*) FROM studio_tests WHERE result_status='PASSED'").fetchone()[0])
            failed = int(db.execute("SELECT COUNT(*) FROM studio_tests WHERE result_status='FAILED'").fetchone()[0])
            minutes = float(db.execute("SELECT COALESCE(SUM(gpu_minutes),0) FROM studio_tests").fetchone()[0])
            cost = float(db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM studio_tests").fetchone()[0])
        return {**totals, "tests_passed": passed, "tests_failed": failed, "tracked_gpu_minutes": round(minutes, 2), "tracked_cost_usd": round(cost, 2), "storage": self.storage_status()}

    def reports(self) -> dict[str, Any]:
        projects = self.list_projects()
        overview = self.overview()
        return {
            "summary": overview,
            "projects": [{
                "project_id": p["project_id"], "title": p["title"], "status": p["status"],
                "scene_count": p["scene_count"], "shot_count": p["shot_count"], "approved_shot_count": p["approved_shot_count"],
                "test_count": p["test_count"], "asset_count": p["asset_count"]
            } for p in projects],
            "test_results": {
                "passed": overview["tests_passed"], "failed": overview["tests_failed"],
                "planned": sum(1 for t in self.list_tests() if t["result_status"] == "PLANNED"),
                "needs_review": sum(1 for t in self.list_tests() if t["result_status"] == "NEEDS_REVIEW")
            },
            "cost_note": "Figures include only costs and GPU minutes explicitly entered in test records; they are not a live provider billing feed."
        }
