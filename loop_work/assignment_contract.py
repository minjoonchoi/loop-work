"""Opt-in assignment v2: explicit responsibility and immutable repair lineage."""
from __future__ import annotations

import re

from .contract import identifier
from .storage import LoopError, digest

V2_FIELDS = {"schema_version", "work_unit_id", "request_revision", "previous_request_hash", "correction_ledger"}
ORIGINS = {"worker_output", "assignment_input", "orchestrator_fixture", "provider_execution", "evidence_staleness"}
STRATEGIES = {
    "worker_output": {"escalate"},
    "assignment_input": {"repair_contract_same_profile"},
    "orchestrator_fixture": {"repair_contract_same_profile"},
    "provider_execution": {"retry_same_profile", "blocked"},
    "evidence_staleness": {"retry_same_profile", "blocked"},
}


def version(request):
    value = request.get("schema_version", 1)
    if type(value) is not int or value not in (1, 2) or value == 1 and "schema_version" in request:
        raise LoopError("Use the legacy unversioned contract or explicit schema_version 2")
    return value


def validate_v2(request):
    if version(request) != 2:
        return
    if not identifier(request.get("work_unit_id")) or request["work_unit_id"] != request.get("id"):
        raise LoopError("v2 id must equal its stable work_unit_id; renaming cannot reset attempts")
    revision = request.get("request_revision")
    if type(revision) is not int or revision < 1:
        raise LoopError("request_revision must be a positive integer")
    previous = request.get("previous_request_hash")
    if revision == 1 and previous is not None or revision > 1 and (not isinstance(previous, str) or not re.fullmatch('[a-f0-9]{64}', previous)):
        raise LoopError("Initial revision needs null previous_request_hash; later revisions need the exact prior request hash")
    if not isinstance(request.get("criteria"), list) or not request["criteria"]:
        raise LoopError("v2 criteria must be a nonempty list")
    for row in request["criteria"]:
        if not isinstance(row, dict) or set(row) != {"id", "description", "execution_owner", "verification_mode"}:
            raise LoopError("v2 criteria require id, description, execution_owner and verification_mode")
        owner, mode = row["execution_owner"], row["verification_mode"]
        if owner not in ("worker", "orchestrator") or mode not in ("source_inspection", "candidate_test", "orchestrator_receipt"):
            raise LoopError("Unknown criterion execution owner or verification mode")
        if (owner == "orchestrator") != (mode == "orchestrator_receipt"):
            raise LoopError("Orchestrator receipt verification belongs exclusively to the orchestrator")
        if owner == "worker" and mode == "candidate_test":
            raise LoopError("Portable read-only workers cannot own candidate execution; use source_inspection or an orchestrator-owned receipt")
    from .corrections import validate_ledger
    validate_ledger(request.get("correction_ledger"), [], [x["id"] for x in request["criteria"]])


def rejection(payload, request):
    if version(request) == 1:
        return {"origin": "unknown", "strategy": None}
    if payload.get("schema_version") != 2 or type(payload.get("schema_version")) is not int:
        raise LoopError("v2 assignments require schema_version 2 assessments")
    value = payload.get("rejection")
    if payload.get("verdict") == "accept":
        if value is not None:
            raise LoopError("Accepted assessment must have null rejection")
        return None
    if not isinstance(value, dict) or set(value) != {"origin", "strategy"} or value.get("origin") not in ORIGINS:
        raise LoopError("Rejected assessment requires a typed origin and strategy")
    if value["strategy"] not in STRATEGIES[value["origin"]]:
        raise LoopError("Rejection origin/strategy combination is not allowed")
    return dict(value)


def validate_revision(request, previous):
    """Caller separately verifies previous candidate and assessment file pins."""
    if version(request) == 1:
        if previous and previous["request"] != request:
            raise LoopError("An assignment is immutable; use a new ID for different work")
        return False
    if not previous:
        if request["request_revision"] != 1:
            raise LoopError("A new work unit must start at revision 1; lineage cannot be skipped")
        return False
    old = previous["request"]
    if old == request:
        return False
    if version(old) != 2 or request["work_unit_id"] != old["work_unit_id"]:
        raise LoopError("Cannot change the original work unit or migrate an active v1 assignment")
    if request["request_revision"] != old["request_revision"] + 1 or request["previous_request_hash"] != digest(old):
        raise LoopError("Contract revision must link the exact immediately previous request")
    decision = previous.get("assessment", {}).get("rejection")
    if previous["status"] != "rejected" or decision not in (
            {"origin": "assignment_input", "strategy": "repair_contract_same_profile"},
            {"origin": "orchestrator_fixture", "strategy": "repair_contract_same_profile"}):
        raise LoopError("Only an assessed input/fixture rejection authorizes contract repair at the same profile")
    for key in ("id", "kind", "work_unit_id", "write_paths", "deliverables", "depends_on"):
        if request[key] != old[key]:
            raise LoopError("Contract repair cannot broaden the frozen contribution: " + key)
    if (set(x["id"] for x in request["criteria"]) != set(x["id"] for x in old["criteria"])
            or request["planning"]["goal_criteria"] != old["planning"]["goal_criteria"]):
        raise LoopError("Contract repair must preserve criterion identity and parent coverage")
    if ({row["id"]: row["description"] for row in request["criteria"]}
            != {row["id"]: row["description"] for row in old["criteria"]}):
        raise LoopError("Contract repair cannot weaken or rewrite criterion descriptions")
    if not set(old["prohibited"]) <= set(request["prohibited"]):
        raise LoopError("Contract repair must retain all original prohibitions; stricter additions are allowed")
    ranks = {"low": 0, "medium": 1, "high": 2}
    if any(ranks[request["planning"][key]] < ranks[old["planning"][key]] for key in ("complexity", "risk", "uncertainty")):
        raise LoopError("Contract repair cannot lower recorded complexity, risk or uncertainty")
    from .corrections import validate_ledger
    validate_ledger(request["correction_ledger"], old["correction_ledger"], [x["id"] for x in request["criteria"]])
    return True


def coverage(value, request):
    """Normalize only for legacy structural validation; keep original result pinned."""
    owners = {row["id"]: row["execution_owner"] for row in request["criteria"]}
    normalized = []
    for row in value["coverage"]:
        if not isinstance(row, dict) or set(row) != {"criterion_id", "satisfied", "evidence"}:
            raise LoopError("v2 coverage needs criterion_id, satisfied and evidence")
        owner = owners.get(row["criterion_id"])
        satisfied = row["satisfied"]
        if owner == "orchestrator":
            if satisfied is not None:
                raise LoopError("Worker cannot attest orchestrator-owned verification; return satisfied null (pending)")
        elif type(satisfied) is not bool:
            raise LoopError("Worker-owned coverage requires a boolean satisfaction value")
        normalized.append({**row, "satisfied": True if owner == "orchestrator" else satisfied})
    return normalized


def contribution_signature(request):
    """Catch exact renamed contributions, not arbitrary semantic paraphrases."""
    def text(value):
        return " ".join(value.casefold().split()).rstrip(".。")
    return digest({"kind": request["kind"], "read_paths": sorted(request["read_paths"]),
        "write_paths": sorted(request["write_paths"]),
        "deliverables": sorted(text(row["description"]) for row in request["deliverables"]),
        "criteria": sorted(text(row["description"]) for row in request["criteria"]),
        "goal_criteria": sorted(request["planning"]["goal_criteria"])})


def reject_duplicate_unit(request, records, task_id, location_id):
    if version(request) != 2:
        return
    signature = contribution_signature(request)
    for record in records:
        if (record.get("task_id") != task_id or record.get("location_id") != location_id
                or record["request"]["id"] == request["id"]):
            continue
        prior = [record["request"]] + [row["request"] for row in record.get("history", []) if "request" in row]
        if any(contribution_signature(old) == signature for old in prior):
            raise LoopError("Exact contribution already belongs to another work unit; preserve its original lineage and attempts")
