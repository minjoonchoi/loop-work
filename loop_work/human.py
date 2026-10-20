"""Local human decisions; records never confer gate or external-action authority."""
from __future__ import annotations

import copy
import json
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import re

from .contract import identifier
from .storage import LoopError, digest, file_hash, locked, now

KIND = "human-request"
CLOSED = {"declined", "executed", "failed"}
DECISIONS = {"decision": {"answer", "reject"}, "approval": {"approve", "reject"},
             "manual_action": {"resolved", "reject"}}


def public_requests(records, task_id):
    """Raw human input is data, never an inferred response or new goal authority."""
    return [{key: copy.deepcopy(item[key]) for key in
             ("id", "task_id", "session_id", "kind", "title", "question", "options", "action",
              "status", "revision", "response", "execution", "superseded_by")}
            for item in records if item["task_id"] == task_id]


class HumanDesk:
    def __init__(self, knowledge):
        self.knowledge = knowledge

    def list(self, session_id=None, task_id=None, include_closed=False):
        tasks = [item for item in self.knowledge.list("task")
                 if (session_id is None or item["session_id"] == session_id)
                 and (task_id is None or item["id"] == task_id)]
        ids = {item["id"] for item in tasks}
        requests = [item for item in self.knowledge.list(KIND) if item["task_id"] in ids
                    and (include_closed or not item.get("superseded_by") and (
                        item["status"] in ("pending", "declined", "failed") or
                        item["status"] == "answered" and item["action"] == "resume_task"
                        and item["execution"] is None and item["response"]["decision"] in ("approve", "resolved")))]
        return {"requests": requests, "tasks": [{key: item.get(key) for key in
                ("id", "session_id", "kind", "title", "phase")} for item in tasks]}

    def show(self, request_id):
        return self.knowledge.get(KIND, request_id)

    def _get(self, kind, key, db=None):
        if db is None:
            return self.knowledge.get(kind, key)
        row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            raise LoopError("Unknown " + kind + ": " + key)
        return json.loads(row[0])

    def _items(self, kind, db=None):
        if db is None:
            return self.knowledge.list(kind)
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM records WHERE kind=? ORDER BY id", (kind,))]

    def _snapshot(self, task_id, db=None):
        task = self._get("task", task_id, db)
        locations = [self._get("location", key, db) for key in task["locations"]]
        observed = self.knowledge.observe(locations)
        # Feedback control versions are session-wide, but approval authority is
        # task-scoped. All relevant pause/resume/constraint rows carry task_id.
        related = {kind: [item for item in self._items(kind, db)
                         if item.get("task_id") == task_id or kind == "worker-budget" and item["id"] == task_id]
                   for kind in ("delegation", "team", "worker-budget", "feedback")}
        development = None
        if task["kind"] == "development":
            from .engine import Engine
            development = Engine(Path(locations[0]["root"]), task["goal_id"], self.knowledge).load()
        # Development task rows are regenerated navigation views. Their
        # next_action/progress/evidence-current fields are not execution state;
        # the original state/contract/discovery above retain that authority.
        derived = {"next_action", "progress", "freshness", "updated_at", "result"} if task["kind"] == "development" else set()
        semantic_task = {key: value for key, value in task.items() if key not in derived}
        session = self._get("session", task["session_id"], db)
        session_authority = {"id": session["id"], "provider": session["provider"],
                             "enabled": session.get("harness", {}).get("enabled", False)}
        return digest({"task": semantic_task, "session": session_authority,
                       "observed": observed, "related": related, "development": development})

    @staticmethod
    def _text(value, label, maximum=2000):
        if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
            raise LoopError(label + " must be a nonempty bounded string")
        return value

    def _evidence(self, evidence, task):
        if not isinstance(evidence, list):
            raise LoopError("Human evidence must be a list of ref/modepin pairs")
        roots = [Path(self.knowledge.get("location", key)["root"]).resolve() for key in task["locations"]]
        roots.append(self.knowledge.home.resolve())
        for row in evidence:
            if not isinstance(row, dict) or set(row) != {"ref", "modepin"}:
                raise LoopError("Human evidence requires exact ref and modepin")
            if not isinstance(row["ref"], str) or not isinstance(row["modepin"], str) or not re.fullmatch("[0-9a-f]{64}", row["modepin"]):
                raise LoopError("Human evidence requires a path and mode-aware 64-character pin")
            path = Path(row["ref"])
            if not path.is_absolute():
                raise LoopError("Human evidence must be an absolute task/knowledge path")
            root = next((root for root in roots if path.resolve().is_relative_to(root)), None)
            if root is None:
                raise LoopError("Human evidence is outside this task's locations")
            for part in (path, *path.parents):
                if part.resolve() == root:
                    break
                if part.is_symlink():
                    raise LoopError("Human evidence cannot follow task-local symlinks")
            if not path.is_file() or file_hash(path) != row["modepin"]:
                raise LoopError("Human evidence pin is stale or unavailable")

    def create(self, task_id, payload):
        required = {"id", "kind", "title", "question", "options", "action"}
        if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - required - {"evidence", "supersedes"}:
            raise LoopError("Human request requires id/kind/title/question/options/action")
        if not isinstance(payload["id"], str) or not identifier(payload["id"]):
            raise LoopError("Invalid human request ID")
        if not isinstance(payload["kind"], str) or payload["kind"] not in DECISIONS or payload["action"] not in (None, "resume_task"):
            raise LoopError("Unsupported human request kind or action")
        if payload["kind"] == "decision" and payload["action"] is not None:
            raise LoopError("A decision records an answer and cannot execute an action")
        self._text(payload["title"], "Title", 240)
        self._text(payload["question"], "Question")
        if not isinstance(payload["options"], list) or len(payload["options"]) > 12:
            raise LoopError("Human options must contain at most twelve strings")
        for option in payload["options"]:
            self._text(option, "Option", 240)
        if len(set(payload["options"])) != len(payload["options"]):
            raise LoopError("Human options must be distinct")
        with locked(self.knowledge.home / "human-locks" / "desk"):
            if self.knowledge.get(KIND, payload["id"], required=False):
                raise LoopError("Human request ID already exists; preserve its immutable history")
            task = self.knowledge.get("task", task_id)
            supersedes = payload.get("supersedes", [])
            if (not isinstance(supersedes, list) or not all(isinstance(key, str) for key in supersedes)
                    or len(set(supersedes)) != len(supersedes) or payload["id"] in supersedes):
                raise LoopError("Supersedes must contain distinct earlier request IDs without cycles")
            earlier = [self.show(key) for key in supersedes]
            if any(item["task_id"] != task_id or item.get("superseded_by") for item in earlier):
                raise LoopError("Only unsuperseded requests from this same task may be replaced")
            self._evidence(payload.get("evidence", []), task)
            record = {**copy.deepcopy(payload), "evidence": copy.deepcopy(payload.get("evidence", [])),
                      "task_id": task_id, "session_id": task["session_id"], "status": "pending", "revision": 1,
                      "response": None, "execution": None, "fingerprint": self._snapshot(task_id),
                      "created_at": now(), "history": [], "supersedes": list(supersedes), "superseded_by": None}
            # All new-request validation precedes the atomic replacement links.
            with self.knowledge.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                for item in earlier:
                    previous = {key: copy.deepcopy(value) for key, value in item.items() if key != "history"}
                    replaced = {**item, "superseded_by": record["id"], "revision": item["revision"] + 1,
                                "history": item["history"] + [previous], "updated_at": now()}
                    self.knowledge.put(KIND, replaced, db)
                self.knowledge.put(KIND, record, db)
            return record

    def _current(self, request_id, expected_revision):
        return self._checked(request_id, expected_revision)

    def _checked(self, request_id, expected_revision, db=None):
        record = self._get(KIND, request_id, db)
        if record.get("superseded_by"):
            raise LoopError("Human request was superseded; respond only to its pending replacement")
        if type(expected_revision) is not int or expected_revision != record["revision"]:
            raise LoopError("Human request revision conflict; reload the current request")
        if record["fingerprint"] != self._snapshot(record["task_id"], db):
            raise LoopError("Human request is stale: task, source, controls or budget changed; create a new request")
        self._evidence(record["evidence"], self._get("task", record["task_id"], db))
        return record

    def _save(self, record, *, db=None, **changes):
        prior = {key: copy.deepcopy(value) for key, value in record.items() if key != "history"}
        record = {**record, **changes, "revision": record["revision"] + 1,
                  "history": record["history"] + [prior], "updated_at": now()}
        self.knowledge.put(KIND, record, db)
        return record

    def respond(self, request_id, response, expected_revision):
        with locked(self.knowledge.home / "human-locks" / "desk"), ExitStack() as locks:
            original = self.show(request_id)
            task = self.knowledge.get("task", original["task_id"])
            for root in sorted(self.knowledge.get("location", key)["root"] for key in task["locations"]):
                locks.enter_context(locked(Path(root)))
            record = self._current(request_id, expected_revision)
            if record["status"] != "pending":
                raise LoopError("Human request already has a response; create a new request to correct it")
            if not isinstance(response, dict) or set(response) != {"decision", "text"}:
                raise LoopError("Human response requires exact decision and text")
            if not isinstance(response["decision"], str) or response["decision"] not in DECISIONS[record["kind"]]:
                raise LoopError("Response decision does not match the human request kind")
            self._text(response["text"], "Human response", 4000)
            with self.knowledge.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                record = self._checked(request_id, expected_revision, db)
                return self._save(record, db=db, response=copy.deepcopy(response),
                                  status="declined" if response["decision"] == "reject" else "answered")

    def _resume_budget(self, task, db=None):
        if task["kind"] == "development":
            return
        execution = (task.get("goal") or {}).get("execution", task.get("preflight_execution", {}))
        budgets = [item for item in self._items("worker-budget", db) if item["id"] == task["id"]]
        calls = budgets[0]["calls"] if budgets else 0
        elapsed = ((datetime.now(timezone.utc) - datetime.fromisoformat(task["started_at"])).total_seconds()
                   if task.get("started_at") else 0)
        if calls >= execution.get("max_worker_calls", 40) or elapsed >= execution.get("max_run_seconds", 14400):
            raise LoopError("Task call/time budget exhausted; human approval cannot reset it")

    def execute(self, request_id, expected_revision):
        with locked(self.knowledge.home / "human-locks" / "desk"), ExitStack() as locks:
            original = self.show(request_id)
            task = self.knowledge.get("task", original["task_id"])
            roots = sorted(self.knowledge.get("location", key)["root"] for key in task["locations"])
            for root in roots:
                locks.enter_context(locked(Path(root)))
            record = self._current(request_id, expected_revision)
            if (record["status"] != "answered" or record["execution"] is not None
                    or record["action"] != "resume_task" or record["response"]["decision"] not in ("approve", "resolved")):
                raise LoopError("Only an unexecuted, explicitly approved/resolved resume_task can execute")
            task = self.knowledge.get("task", record["task_id"])
            from .delegation import Delegation
            for retained in self.knowledge.list("delegation"):
                if retained.get("task_id") == task["id"]:
                    location = self.knowledge.get("location", retained["location_id"])
                    Delegation(self.knowledge, task["id"], Path(location["root"])).validate_retained_evidence(retained)
            self._resume_budget(task)
            if task["phase"] != "blocked":
                raise LoopError("Only a currently blocked task can resume")
            with self.knowledge.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                record = self._checked(request_id, expected_revision, db)
                record = self._save(record, db=db, execution={"action": "resume_task", "state": "claimed", "at": now()})
            def authority_check(db):
                self._checked(request_id, record["revision"], db)
                self._resume_budget(self._get("task", record["task_id"], db), db)
            try:
                if task["kind"] == "development":
                    from .engine import Engine
                    location = self.knowledge.get("location", task["locations"][0])
                    Engine(Path(location["root"]), task["goal_id"], self.knowledge).resume(authority_check=authority_check)
                else:
                    from .work import Work
                    Work(self.knowledge).resume(task["id"], authority_check=authority_check)
                return self._save(record, status="executed", execution={"action": "resume_task", "state": "executed", "at": now()})
            except (LoopError, OSError, ValueError) as exc:
                return self._save(record, status="failed", execution={"action": "resume_task", "state": "failed", "error": str(exc), "at": now()})
