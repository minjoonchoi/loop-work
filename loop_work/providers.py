"""Read-only CLI transports for bounded workers and independent reviews."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from .process import Cancelled, execute
from .storage import LoopError, read_json, write_json


def obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}


class InvalidResult(LoopError):
    """A completed call produced unusable output, not a transport/authority failure."""

REVIEW_SCHEMA = obj({
    "verdict": {"type": "string", "enum": ["pass", "revise", "blocked"]},
    "summary": STRING,
    "findings": {"type": "array", "items": obj({
        "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
        "target": STRING, "evidence": STRING, "remedy": STRING})},
    "questions": {"type": "array", "items": STRING},
    "coverage": {"type": "array", "items": obj({
        "acceptance_id": STRING, "satisfied": {"type": "boolean"}, "evidence": STRING})},
})


def review_selection(implementer):
    """Prefer an installed opposite CLI; never mask a failing invocation."""
    opposite = reviewer(implementer)
    allowed = {"claude", "codex"}
    managed = bool(os.environ.get("LOOP_BENCH_PROFILE"))
    if managed:
        allowed = set(read_json(Path(os.environ["LOOP_BENCH_PROFILE"]))["models"])
    # Managed calls resolve absolute wrappers, not the caller's reconstructed
    # PATH. A configured but broken wrapper is a configuration error, not an
    # absent opposite CLI permitting a different reviewer.
    available = {}
    for provider in ("claude", "codex"):
        if provider not in allowed:
            available[provider] = False
            continue
        try:
            available[provider] = bool(executable_for(provider))
        except LoopError:
            if managed:
                raise
            available[provider] = False
    selected = opposite if available[opposite] else implementer
    return {"provider": selected, "implementer": implementer,
            "mode": "cross_provider" if selected != implementer else "same_provider_fresh",
            "reason": "opposite CLI available" if selected != implementer else "opposite CLI absent at preflight",
            "available": available}


def reviewer(implementer):
    if implementer not in ("claude", "codex"):
        raise LoopError("Unknown implementer")
    return "codex" if implementer == "claude" else "claude"


def effort_args(provider, effort):
    if effort is None:
        return []
    if not isinstance(effort, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', effort) or effort in ('auto', 'default'):
        raise LoopError('Use an explicit effort level supported by the selected model; no automatic fallback')
    if provider == 'codex':
        return ['-c', 'model_reasoning_effort=' + json.dumps(effort),
                '-c', 'plan_mode_reasoning_effort=' + json.dumps(effort)]
    if provider == 'claude':
        return ['--effort', effort]
    raise LoopError('Unknown effort provider')


def executable_for(provider):
    """Managed benchmark calls must not depend on a tool shell's PATH."""
    profile_path = os.environ.get('LOOP_BENCH_PROFILE')
    if profile_path:
        path = Path(profile_path)
        if not path.is_absolute() or path.is_symlink():
            raise LoopError('Invalid benchmark transport profile path')
        profile = read_json(path)
        if provider not in profile.get('models', {}):
            raise LoopError('Provider is outside the frozen benchmark catalog')
        wrapper = path.parent / 'bin' / provider
        if wrapper.is_symlink() or not wrapper.is_file() or not os.access(wrapper, os.X_OK):
            raise LoopError('Required benchmark wrapper is unavailable; no direct CLI fallback')
        return str(wrapper)
    executable = shutil.which(provider)
    if not executable:
        raise LoopError(f"Required CLI is not installed: {provider}")
    return executable


def command(provider, root, directory, schema=None, outside_git=False, model=None, effort=None):
    executable = executable_for(provider)
    schema_path = directory / "schema.json"
    if provider == "codex":
        return [executable, "--ask-for-approval", "never", "--sandbox", "read-only",
                "exec", *(["--model", model] if model else []), *effort_args(provider, effort), *(["--skip-git-repo-check"] if outside_git else []), "--ephemeral", "--output-schema", str(schema_path),
                "--output-last-message", str(directory / "answer.json"), "-"]
    if provider == "claude":
        # An explicit same-model fallback overrides a persisted availability
        # chain without guessing an undocumented empty/disable flag. These are
        # session-only choices; managed provider policies remain authoritative.
        selection = (["--model", model, "--fallback-model", model] if model else [])
        return [executable, "-p", *selection, *effort_args(provider, effort),
                "--settings", '{"switchModelsOnFlag":false}', "--output-format", "json", "--json-schema",
                json.dumps(schema or REVIEW_SCHEMA, separators=(",", ":")),
                "--permission-mode", "dontAsk", "--tools", "Read,Glob,Grep",
                "--allowedTools", "Read,Glob,Grep", "--disallowedTools", "AskUserQuestion,mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--no-session-persistence"]
    raise LoopError(f"Unknown provider: {provider}")


def doctor(root, directory, required=None):
    reports = {}
    for provider in ("claude", "codex"):
        if required is not None and provider not in required:
            reports[provider] = {"ok": False, "skipped": True, "reason": "not selected for this review"}
            continue
        try:
            executable = executable_for(provider)
        except LoopError as exc:
            reports[provider] = {"ok": False, "error": str(exc)}
            continue
        result = execute([executable, "--version"], root, directory / provider, 15)
        reports[provider] = {"ok": result["exit_code"] == 0 and not result["timed_out"],
                             "executable": executable, "process": result,
                             "version": Path(result["stdout"]).read_text(errors="replace").strip()[:200]}
    return {"ok": all(reports[p]["ok"] for p in (required or reports)), "providers": reports,
            "note": "Version checks do not prove authentication. plan-review is the live reviewer preflight."}


def validate_review(value, expected_ids, phase):
    def string(x):
        return isinstance(x, str) and bool(x.strip())
    if not isinstance(value, dict) or set(value) != set(REVIEW_SCHEMA["properties"]):
        raise LoopError("Reviewer returned an invalid object")
    if value["verdict"] not in ("pass", "revise", "blocked") or not string(value["summary"]):
        raise LoopError("Reviewer returned an invalid verdict or summary")
    if not isinstance(value["questions"], list) or not all(string(x) for x in value["questions"]):
        raise LoopError("Reviewer questions must be strings")
    if phase != "plan" and value["questions"]:
        raise LoopError("Execution reviewer tried to ask questions; resolve using frozen decisions or report blocked")
    if not isinstance(value["findings"], list):
        raise LoopError("Reviewer findings must be an array")
    for item in value["findings"]:
        if (not isinstance(item, dict) or set(item) != {"severity", "target", "evidence", "remedy"}
                or item["severity"] not in ("blocker", "major", "minor")
                or not all(string(item[x]) for x in ("target", "evidence", "remedy"))):
            raise LoopError("Reviewer finding is incomplete")
    if not isinstance(value["coverage"], list):
        raise LoopError("Reviewer coverage must be an array")
    ids = []
    for item in value["coverage"]:
        if (not isinstance(item, dict) or set(item) != {"acceptance_id", "satisfied", "evidence"}
                or not string(item["acceptance_id"]) or type(item["satisfied"]) is not bool
                or not string(item["evidence"])):
            raise LoopError("Reviewer coverage is incomplete")
        ids.append(item["acceptance_id"])
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise LoopError("Reviewer must cover every requested acceptance ID exactly once")
    passed = (value["verdict"] == "pass" and not value["findings"] and not value["questions"]
              and all(x["satisfied"] for x in value["coverage"]))
    if value["verdict"] == "pass" and not passed:
        raise LoopError("Reviewer claimed pass with unresolved findings, questions, or unmet acceptance")
    return passed


def structured_call(provider, root, directory, prompt, timeout, schema, outside_git=False, model=None, effort=None, cancel=None):
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "schema.json", schema)
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    env = {'CLAUDE_CODE_EFFORT_LEVEL': effort} if provider == 'claude' and effort else {}
    if os.environ.get('LOOP_BENCH_PROFILE'):
        env['LOOP_BENCH_RECEIPT'] = str((directory / 'process.json').resolve())
    result = execute(command(provider, root, directory, schema, outside_git, model, effort), root, directory, timeout,
                     prompt=prompt, env_overrides=env, **({"cancel":cancel} if cancel is not None else {}))
    result['profile_observation'] = profile_observation(provider, model, effort, result.get('argv', []),
                                                        directory / 'stdout.log')
    write_json(directory / "process.json", result)
    if result.get("cancelled"):
        raise Cancelled(result.get("cancel_reason") or "Task interrupted by user")
    if result["exit_code"] != 0 or result["timed_out"]:
        raise LoopError(f"{provider} call failed; inspect {directory / 'stderr.log'}")
    source = directory / ("answer.json" if provider == "codex" else "stdout.log")
    if not source.exists():
        raise LoopError("Missing worker/reviewer result; inspect provider execution")
    if source.stat().st_size > 1024 * 1024:
        raise InvalidResult("Oversized worker/reviewer result")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise InvalidResult("Worker/reviewer returned malformed JSON") from exc
    if provider == "claude":
        if isinstance(value, dict) and (value.get("is_error") or value.get("permission_denials")):
            raise LoopError("Claude call failed or reported denied permissions")
        if not isinstance(value, dict) or "structured_output" not in value:
            raise InvalidResult("Claude returned an invalid structured-output envelope")
        value = value.get("structured_output")
    return value


def profile_observation(provider, model, effort, argv, stdout_path):
    """Keep requested, locally constructed and unobserved backend layers apart.

    JSON usage is a CLI observation, not billing or backend attestation. No
    version/authentication/configuration probes are performed by this observer.
    """
    local = {'provider': provider, 'model': None, 'effort': None}
    for index, argument in enumerate(argv[:-1]):
        if argument == '--model':
            local['model'] = argv[index + 1]
        elif provider == 'claude' and argument == '--effort':
            local['effort'] = argv[index + 1]
        elif provider == 'codex' and argument == '-c':
            setting = argv[index + 1]
            if setting.startswith('model_reasoning_effort='):
                try:
                    local['effort'] = json.loads(setting.split('=', 1)[1])
                except ValueError:
                    pass
    usage = []
    path = Path(stdout_path)
    try:
        lines = path.read_text(errors='replace').splitlines() if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024 else []
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get('usage'), dict):
            usage.append(event['usage'])
    return {'version': 1, 'requested_profile': {'provider': provider, 'model': model, 'effort': effort},
            'local_resolved_profile': local, 'local_source': 'process.argv',
            'backend_attested_profile': None, 'cli_version': None,
            'support_status': 'unknown', 'support_scope': 'safe argument syntax only; model-specific support unverified',
            'usage': usage or None, 'receipt_source': str(path) if usage else None,
            'price_version': None, 'currency': None, 'cost': None}


def review(provider, root, directory, prompt, timeout, expected_ids, phase, model=None, effort=None, cancel=None):
    value = structured_call(provider, root, directory, prompt, timeout, REVIEW_SCHEMA, model=model, effort=effort, **({"cancel":cancel} if cancel is not None else {}))
    passed = validate_review(value, expected_ids, phase)
    write_json(directory / "review.json", value)
    return {"provider": provider, "model": model, "effort": effort, "passed": passed, "result": value,
            "artifact": str(directory / "review.json")}
