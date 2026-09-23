"""Transactional persistence: immutable imported output, versioned human decisions."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .adapter import normalize, digest


def now():
    return datetime.now(timezone.utc).isoformat()


def required_text(value, label, maximum=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} is required (maximum {maximum} characters).")
    return value.strip()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL, raw TEXT NOT NULL, sha TEXT NOT NULL, origin TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS items(run TEXT, id TEXT, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'unreviewed', selected TEXT, PRIMARY KEY(run,id));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, run TEXT NOT NULL, item TEXT NOT NULL, created TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def import_run(self, raw, title, origin="import"):
        items = normalize(raw)
        title = required_text(title, "Run title", 200)
        rid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (rid, title, now(), json.dumps(raw, allow_nan=False), digest(raw), origin))
            for item in items:
                db.execute("INSERT INTO items(run,id,data) VALUES(?,?,?)", (rid, item["id"], json.dumps(item)))
        return self.run(rid)

    def list_runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT r.id,r.title,r.created,r.origin,r.sha,COUNT(i.id) item_count,SUM(i.status!='unreviewed') reviewed FROM runs r LEFT JOIN items i ON i.run=r.id GROUP BY r.id ORDER BY r.created DESC")]

    def run(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError("Run not found.")
            result = dict(row)
            result["raw"] = json.loads(result["raw"])
            result["items"] = [{**json.loads(i["data"]), "version": i["version"], "status": i["status"], "selected": i["selected"]} for i in db.execute("SELECT * FROM items WHERE run=? ORDER BY rowid", (rid,))]
            result["events"] = [{"id": e["id"], "item": e["item"], "created": e["created"], **json.loads(e["data"])} for e in db.execute("SELECT * FROM events WHERE run=? ORDER BY rowid", (rid,))]
            return result

    def event(self, rid, iid, payload, kind="comment"):
        author = required_text(payload.get("author"), "Reviewer name", 100)
        text = required_text(payload.get("text"), "Comment or decision reason")
        version = payload.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("An item version is required.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM items WHERE run=? AND id=?", (rid, iid)).fetchone()
            if row is None:
                raise KeyError("Attribute not found.")
            if row["version"] != version:
                raise Conflict("This attribute changed in another view. Refresh before submitting.")
            parent = payload.get("parent")
            if parent is not None and (not isinstance(parent, str) or not parent):
                raise ValueError("Reply target must be a recorded post ID or null.")
            if parent and not db.execute("SELECT id FROM events WHERE id=? AND run=? AND item=?", (parent, rid, iid)).fetchone():
                raise ValueError("Reply target is not a post on this attribute.")
            refs = payload.get("references", [])
            candidates = {c["id"] for c in json.loads(row["data"])["candidates"]}
            if not isinstance(refs, list) or any(not isinstance(r, str) or r not in candidates for r in refs):
                raise ValueError("References must identify recorded candidates on this attribute.")
            event = {"kind": kind, "author": author, "author_type": "human", "text": text, "version": version, "parent": parent, "references": refs}
            if kind == "decision":
                action, selected = payload.get("status"), payload.get("selected")
                if action not in {"accepted", "rejected", "needs_review"}:
                    raise ValueError("Unknown review decision.")
                if action == "accepted" and selected not in candidates:
                    raise ValueError("Select a recorded validated candidate before accepting.")
                if action != "accepted":
                    selected = None
                db.execute("UPDATE items SET version=version+1,status=?,selected=? WHERE run=? AND id=?", (action, selected, rid, iid))
                event.update(status=action, selected=selected, new_version=version+1)
            eid = uuid.uuid4().hex
            db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (eid, rid, iid, now(), json.dumps(event)))
        return self.run(rid)

    def agent_event(self, rid, iid, event):
        # Trusted worker output is still checked against the stored candidate set.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data,version FROM items WHERE run=? AND id=?", (rid, iid)).fetchone()
            if row is None:
                raise KeyError("Attribute not found.")
            if row["version"] != event["version"]:
                raise Conflict("Review changed during agent execution; proposed response was not applied.")
            allowed = {c["id"] for c in json.loads(row["data"])["candidates"]}
            proposal = event.get("proposed_candidate")
            if proposal is not None and proposal not in allowed:
                raise ValueError("Agent proposed an unknown candidate.")
            event["text"] = required_text(event.get("text"), "Agent response", 20000)
            event.update(kind="agent_response", author_type="agent")
            db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (uuid.uuid4().hex, rid, iid, now(), json.dumps(event)))
        return self.run(rid)

    def save_job(self, job):
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (job["id"], job["created"], json.dumps(job)))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM jobs ORDER BY created DESC LIMIT 100")]
