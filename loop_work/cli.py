from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import sqlite3
import uuid

from . import providers
from .contract import validate
from .engine import Engine
from .harness import Harness
from .session import Session
from .knowledge import KnowledgeBase, project_root
from .work import KINDS, Work
from .storage import LoopError, locked, read_json, repository


def parser():
    result = argparse.ArgumentParser(description="loop-work: goal setting, work and reusable local knowledge")
    result.add_argument("--root", type=Path, default=Path.cwd(), help="Target repository root")
    result.add_argument("--knowledge-home", type=Path, help="Local knowledge directory (default: LOOP_KB_HOME or ~/.loop-work/data; existing legacy DB retained)")
    commands = result.add_subparsers(dest="command", required=True)
    bench = commands.add_parser("bench", help="Compare the same tasks with and without the current harness")
    bench_commands = bench.add_subparsers(dest="bench_command", required=True)
    source = Path(__file__).resolve().parent.parent
    for name in ("plan", "run", "check"):
        sub = bench_commands.add_parser(name)
        sub.add_argument("--suite", type=Path, required=name != "check", default=source / "benchmarks/suite.json")
        sub.add_argument("--candidate", type=Path, required=name != "check", default=source)
        sub.add_argument("--codex-model")
        sub.add_argument("--claude-model")
        sub.add_argument("--codex-effort")
        sub.add_argument("--claude-effort")
        sub.add_argument("--routing-profile", type=Path, help="Explicit worker routing policy; omitted uses the fixed benchmark models and efforts")
        sub.add_argument("--provider", choices=("claude", "codex"), action="append", required=name != "check")
        sub.add_argument("--repeats", type=int, default=3)
        sub.add_argument("--seed", type=int, default=0)
        sub.add_argument("--environment", required=name != "check", help="Fixed host, credentials and configuration profile description")
        if name in ("run", "check"):
            sub.add_argument("--output", type=Path, required=name == "run")
            sub.add_argument("--trial-plan", type=Path, help="Sealed exact trial IDs and workspace roots; no trust settings are changed")
        if name == "check":
            sub.add_argument("--history", type=Path, help="Persistent before/after baselines; defaults beside the candidate source")
            sub.add_argument("--judge-provider", choices=("claude", "codex"), default="codex")
            sub.add_argument("--judge-model", help="Defaults to the chosen judge provider's model")
            sub.add_argument("--judge-effort", help="Defaults to the chosen judge provider's effort")
            sub.add_argument("--judge-repeats", type=int, default=2)
            sub.add_argument("--dry-run", action="store_true", help="Validate and show the frozen comparison without model calls")
    for name in ("report", "gate", "judge", "proposal"):
        sub = bench_commands.add_parser(name)
        sub.add_argument("run", type=Path)
        if name in ("report", "gate"):
            sub.add_argument("--judgments", type=Path)
        if name == "gate":
            sub.add_argument("--candidate", type=Path, required=True)
            sub.add_argument("--suite", type=Path, required=True)
        if name == "judge":
            sub.add_argument("--provider", choices=("claude", "codex"), required=True)
            sub.add_argument("--model", required=True)
            sub.add_argument("--effort", required=True)
            sub.add_argument("--repeats", type=int, default=2)
        if name == "proposal":
            sub.add_argument("--input", type=Path, required=True)
    board = commands.add_parser("board", help="Track and approve work from the Obsidian vault")
    board_commands = board.add_subparsers(dest="board_command")
    board.set_defaults(board_command="open",vault=None,project=None,session=None,task=None,port=0)
    for name in ("open", "_desktop", "start", "status", "stop", "list", "show"):
        sub = board_commands.add_parser(name)
        sub.add_argument("--vault", type=Path, help="Explicit vault opt-in for a custom knowledge store")
        sub.add_argument("--project", help="Restrict this board to one project")
        sub.add_argument("--session")
        sub.add_argument("--task")
        if name in ("open", "_desktop", "start"):
            sub.add_argument("--port", type=int, default=0)
        if name == "_desktop":
            sub.add_argument("--target-root", type=Path)
        elif name == "show":
            sub.add_argument("id")
            sub.add_argument("--kind", choices=("task", "human-request"), default="human-request")
    human = commands.add_parser("human", help="Local human decisions and explicitly bounded actions")
    human_commands = human.add_subparsers(dest="human_command", required=True)
    for name in ("list",):
        sub = human_commands.add_parser(name)
        sub.add_argument("--session")
        sub.add_argument("--task")
        if name == "list":
            sub.add_argument("--include-closed", action="store_true")
    human_commands.add_parser("show").add_argument("id")
    request = human_commands.add_parser("request")
    request.add_argument("task")
    request.add_argument("--input", type=Path, required=True)
    for name in ("respond", "execute"):
        sub = human_commands.add_parser(name)
        sub.add_argument("id")
        sub.add_argument("--expected-revision", type=int, required=True)
        if name == "respond":
            sub.add_argument("--input", type=Path, required=True)
    harness = commands.add_parser("harness", help="Bind or release the harness for one explicit task")
    harness_commands = harness.add_subparsers(dest="harness_command", required=True)
    enabled = harness_commands.add_parser("on")
    enabled.add_argument("--provider", choices=("claude", "codex"), required=True)
    enabled.add_argument("--session", help="Owning session ID of the explicit task")
    enabled.add_argument("--task", required=True, help="Existing common-work or development task record ID")
    for name in ("status", "off"):
        harness_commands.add_parser(name).add_argument("session_id")
    orchestration = commands.add_parser("orchestration", help="Restore compact parent context and record user feedback")
    orchestration_commands = orchestration.add_subparsers(dest="orchestration_command", required=True)
    orchestration_context = orchestration_commands.add_parser("context")
    orchestration_context.add_argument("session_id")
    orchestration_context.add_argument("--task")
    orchestration_context.add_argument("--limit", type=int, choices=range(1, 6), default=5)
    orchestration_feedback = orchestration_commands.add_parser("feedback")
    orchestration_feedback.add_argument("session_id")
    orchestration_feedback.add_argument("--input", type=Path, required=True)
    orchestration_feedback.add_argument("--expected-control-version", type=int, required=True)
    init = commands.add_parser("init", help="Create a draft goal, without implementing code")
    init.add_argument("goal")
    init.add_argument("--title", required=True)
    init.add_argument("--implementer", choices=("claude", "codex"), required=True)
    init.add_argument("--orchestrator", choices=("claude", "codex"), help="Conversation provider; defaults to implementer")
    init.add_argument("--session", help="Reuse the current conversation's session ID for the next goal")
    init.add_argument("--explicit-skill", action="store_true", help="Record creation by an explicit loop-work prompt")
    session = commands.add_parser("session", help="Persist and reuse analysis in the current conversation")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    session_commands.add_parser("open").add_argument("--provider", choices=("claude", "codex"), required=True)
    session_context = session_commands.add_parser("context")
    session_context.add_argument("session_id")
    session_context.add_argument("--goal")
    remember = session_commands.add_parser("remember")
    remember.add_argument("session_id")
    remember.add_argument("--input", type=Path, required=True)
    remember.add_argument("--observed", required=True, help="Revision returned by the context read before analysis")
    for name in ("context", "status", "validate", "doctor", "plan-review", "freeze", "start", "finish", "resume"):
        commands.add_parser(name).add_argument("goal")
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("goal")
    checkpoint.add_argument("--milestone", required=True)
    for name, description in (("delegate", "Execute one explicit bounded worker assignment"),
                              ("team", "Execute a bounded team of explicit worker assignments")):
        delegated = commands.add_parser(name, help=description)
        delegated.add_argument("goal")
        delegated.add_argument("--input", type=Path, required=True)
        delegated.add_argument("--recover", help="Reason for retrying an inspected interrupted worker")
        if name == "delegate":
            delegated.add_argument("--check", action="store_true", help="Read-only dispatch setup check; no provider calls or task changes")
    assessed = commands.add_parser("assess", help="Accept or reject a staged worker candidate against its goal")
    assessed.add_argument("goal")
    assessed.add_argument("--input", type=Path, required=True)
    for name in ("block", "abort"):
        sub = commands.add_parser(name)
        sub.add_argument("goal")
        sub.add_argument("--input", type=Path, required=True) if name == "block" else sub.add_argument("--reason", required=True)
    retired = commands.add_parser("retire", help="Retire a failed assignment obligation with accepted replacements")
    retired.add_argument("goal")
    retired.add_argument("--input", type=Path, required=True)
    note = commands.add_parser("note")
    note.add_argument("goal")
    note.add_argument("--kind", choices=("discovery", "decision", "replan"), required=True)
    note.add_argument("--text", required=True)
    note.add_argument("--evidence", required=True)
    work = commands.add_parser("work", help="Goal setting and work without a mandatory development loop")
    work_commands = work.add_subparsers(dest="work_command", required=True)
    opened = work_commands.add_parser("open")
    opened.add_argument("--kind", choices=KINDS, required=True)
    opened.add_argument("--title", required=True)
    opened.add_argument("--provider", choices=("claude", "codex"), required=True)
    opened.add_argument("--worker", choices=("claude", "codex"), help="Worker provider; defaults to conversation provider")
    opened.add_argument("--path", type=Path, action="append")
    opened.add_argument("--session")
    opened.add_argument("--explicit-skill", action="store_true", help="Record creation by an explicit loop-work prompt")
    for name in ("delegate", "team"):
        delegated = work_commands.add_parser(name)
        delegated.add_argument("task")
        delegated.add_argument("--input", type=Path, required=True)
        delegated.add_argument("--path", type=Path)
        delegated.add_argument("--recover")
        if name == "delegate":
            delegated.add_argument("--check", action="store_true", help="Read-only dispatch setup check; no provider calls or task changes")
    assessed_work = work_commands.add_parser("assess")
    assessed_work.add_argument("task")
    assessed_work.add_argument("--input", type=Path, required=True)
    assessed_work.add_argument("--path", type=Path)
    for name in ("context", "start", "resume"):
        work_commands.add_parser(name).add_argument("task")
    for name in ("goal", "finish"):
        sub = work_commands.add_parser(name)
        sub.add_argument("task")
        sub.add_argument("--input", type=Path, required=True)
    for name in ("block", "abort"):
        sub = work_commands.add_parser(name)
        sub.add_argument("task")
        sub.add_argument("--input", type=Path, required=True) if name == "block" else sub.add_argument("--reason", required=True)
    retired_work = work_commands.add_parser("retire")
    retired_work.add_argument("task")
    retired_work.add_argument("--input", type=Path, required=True)
    note_work = work_commands.add_parser("note")
    note_work.add_argument("task")
    note_work.add_argument("--text", required=True)
    note_work.add_argument("--evidence", required=True)
    knowledge = commands.add_parser("knowledge", help="Project registry, supported facts and historical work")
    knowledge_commands = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_commands.add_parser("projects")
    attach = knowledge_commands.add_parser("attach")
    attach.add_argument("--path", type=Path)
    attach.add_argument("--project")
    for name in ("context", "remember"):
        sub = knowledge_commands.add_parser(name)
        sub.add_argument("--path", type=Path, action="append")
        sub.add_argument("--session")
        sub.add_argument("--task")
        if name == "context":
            sub.add_argument("--query")
            sub.add_argument("--limit", type=int, default=20)
            sub.add_argument("--offset", type=int, default=0)
        else:
            sub.add_argument("--input", type=Path, required=True)
            sub.add_argument("--observed", required=True)
    history = knowledge_commands.add_parser("history")
    history.add_argument("kind", choices=("topic", "task", "delegation"))
    history.add_argument("id")
    get = knowledge_commands.add_parser("get")
    get.add_argument("kind", choices=("topic", "task", "delegation"))
    get.add_argument("id")
    return result


def common_command(args, knowledge):
    if args.command == "knowledge":
        cmd = args.knowledge_command
        if cmd == "projects":
            return {"projects": knowledge.list("project"), "locations": knowledge.list("location")}
        if cmd == "attach":
            return knowledge.attach(args.path or args.root, args.project)
        if cmd == "history":
            return {"current": knowledge.get(args.kind, args.id), "history": knowledge.history(args.kind, args.id)}
        if cmd == "get":
            value = knowledge.get(args.kind, args.id)
            knowledge.document(args.kind, args.id)
            return {"record": value, "document": str(knowledge.home / "views" / args.kind / (args.id + ".md"))}
        locations = [knowledge.attach(path) for path in (args.path or [args.root])]
        if cmd == "context":
            return knowledge.context(locations, args.session, args.task, args.query, args.limit, args.offset)
        return knowledge.remember(read_json(args.input), locations, args.observed, args.session, args.task)
    work = Work(knowledge)
    cmd = args.work_command
    if cmd == "open":
        paths = args.path or [args.root]
        if args.kind == "development":
            if len(paths) != 1:
                raise LoopError("Development gates run per working tree; create a goal per repository in the same session")
            root = repository(project_root(paths[0]))
            with locked(root):
                return Engine(root, "goal-" + uuid.uuid4().hex[:12], knowledge).initialize(
                    args.title, args.worker or args.provider, args.session, args.provider, explicit_skill=args.explicit_skill)
        return work.open(args.kind, args.title, args.provider, paths, args.session, args.worker, explicit_skill=args.explicit_skill)
    if cmd in ("delegate", "team"):
        return getattr(work, cmd)(args.task, read_json(args.input), args.path, args.recover)
    if cmd == "assess":
        return work.assess(args.task, read_json(args.input), args.path)
    if cmd == "goal":
        return work.define(args.task, read_json(args.input))
    if cmd == "finish":
        return work.finish(args.task, read_json(args.input))
    if cmd in ("block", "abort"):
        return work.stop(args.task, read_json(args.input) if cmd == "block" else args.reason, abort=cmd == "abort")
    if cmd == "retire":
        return work.retire(args.task, read_json(args.input))
    if cmd == "note":
        return work.note(args.task, args.text, args.evidence)
    return getattr(work, cmd)(args.task)


def main(argv=None, *, entrypoint=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "bench":
            from . import benchmark, bench_report
            cmd = args.bench_command
            if cmd in ("plan", "run", "check"):
                models = {p: getattr(args, p + "_model") for p in ("codex", "claude")
                          if getattr(args, p + "_model") is not None}
                efforts = {p: getattr(args, p + "_effort") for p in ("codex", "claude")
                           if getattr(args, p + "_effort") is not None}
            if cmd == "check":
                from .bench_check import check
                output = check(models,
                    efforts,
                    candidate=args.candidate, suite=args.suite,
                    providers=args.provider, repeats=args.repeats, seed=args.seed, environment=args.environment,
                    output=args.output, judge_provider=args.judge_provider, judge_model=args.judge_model,
                    judge_effort=args.judge_effort, judge_repeats=args.judge_repeats, dry_run=args.dry_run,
                    history=args.history, routing_profile=args.routing_profile, trial_plan=args.trial_plan)
            elif cmd in ("plan", "run"):
                values = [args.suite, args.candidate,
                          models,
                          args.provider, args.repeats, args.seed, args.environment]
                output = (benchmark.prepare(*values, efforts=efforts, routing_profile=args.routing_profile) if cmd == "plan" else
                          benchmark.run(*values, args.output, efforts=efforts, routing_profile=args.routing_profile, trial_plan=args.trial_plan))
                if cmd == "plan":
                    output["source"] = {k: {"hash": v["hash"]} for k, v in output["source"].items()}
            elif cmd == "judge":
                output = bench_report.judge(args.run, args.provider, args.model, args.repeats, effort=args.effort)
            elif cmd == "gate":
                output = bench_report.gate(args.run, args.candidate, args.suite, args.judgments)
            elif cmd == "proposal":
                output = bench_report.proposal(args.run, args.input)
            else:
                output = bench_report.report(args.run, args.judgments)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 3 if output.get("verdict") == "inconclusive" else 1 if output.get("passed") is False else 0
        checking = (getattr(args, "check", False) and
                    (args.command == "delegate" or args.command == "work" and args.work_command == "delegate"))
        if checking:
            from .delegation import PreflightKnowledge, dispatch_preflight
            knowledge = PreflightKnowledge(args.knowledge_home)
            if args.command == "work":
                task_id, path = args.task, args.path
            else:
                path = repository(project_root(args.root))
                location = knowledge.attach(path)
                task_id = knowledge.development_id(location, args.goal)
            output = dispatch_preflight(knowledge, task_id, read_json(args.input), path, args.recover)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if output["passed"] else 1
        knowledge = KnowledgeBase(args.knowledge_home, vault_home=args.vault if args.command == "board" else None)
        if args.command == "board":
            if args.board_command == "_desktop":
                from .desktop import helper
                return helper(knowledge,args.port,args.session,args.task,args.project,target_root=args.target_root)
            if args.board_command in ("open","start","status","stop"):
                from .desktop import effective_project
                args.project,unattached=effective_project(knowledge,args.project,entrypoint=entrypoint,create=args.board_command not in ("status","stop"))
                if unattached:
                    print(json.dumps({"status":"stopped","project_scope":"unattached"},ensure_ascii=False,indent=2));return 0
            if args.board_command == "open":
                from .desktop import open_app
                output=open_app(knowledge,args.port,args.session,args.task,args.project,entrypoint=entrypoint)
                print(json.dumps(output,ensure_ascii=False,indent=2)); return 0
            if args.board_command in ("start","status","stop"):
                from . import board_service
                operation=getattr(board_service,args.board_command)
                options=dict(session_id=args.session,task_id=args.task,project_id=args.project)
                if args.board_command=="start": options.update(port=args.port)
                output=operation(knowledge,**options)
                # Capability-bearing descriptors remain internal to the native helper.
                output={k:v for k,v in output.items() if k not in ("url","capability")}
                print(json.dumps(output,ensure_ascii=False,indent=2))
                return 0 if output.get("status")!="unknown" else 1
            from .board import Board
            desk = Board(knowledge,args.vault)
            if args.board_command == "list":
                output = desk.list(args.session,args.task,True,**({"project_id":args.project} if args.project is not None else {}))
            else:
                output = desk.show(args.id,args.kind,**({"project_id":args.project} if args.project is not None else {}))
                if ((args.session and output["record"].get("session_id") != args.session)
                        or (args.task and (output["record"].get("task_id") if args.kind == "human-request" else output["id"]) != args.task)):
                    raise LoopError("Document outside board scope")
            print(json.dumps(output,ensure_ascii=False,indent=2))
            return 0
        if args.command == "human":
            from .human import HumanDesk
            desk = HumanDesk(knowledge)
            cmd = args.human_command
            if cmd == "list":
                output = desk.list(args.session, args.task, args.include_closed)
            elif cmd == "show":
                output = desk.show(args.id)
            elif cmd == "request":
                output = desk.create(args.task, read_json(args.input))
            elif cmd == "respond":
                output = desk.respond(args.id, read_json(args.input), args.expected_revision)
            else:
                output = desk.execute(args.id, args.expected_revision)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 1 if output.get("status") == "failed" else 0
        if args.command == "orchestration":
            from .orchestration import Orchestration
            orchestration = Orchestration(knowledge)
            output = (orchestration.context(args.session_id, args.task, args.limit, entrypoint=entrypoint)
                      if args.orchestration_command == "context" else
                      orchestration.feedback(args.session_id, read_json(args.input), args.expected_control_version))
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        if args.command == "harness":
            harness = Harness(knowledge)
            output = (harness.on(args.provider, args.session, args.task) if args.harness_command == "on"
                      else getattr(harness, args.harness_command)(args.session_id))
            base = Path(__file__).resolve().parent.parent
            output["entrypoint"] = str(Path(entrypoint).absolute() if entrypoint else
                                       base / ("loop.py" if (base / "loop.py").is_file() else "scripts/loop.py"))
            output["rules_home"] = str(base / "rules")
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        if args.command in ("work", "knowledge"):
            output = common_command(args, knowledge)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if output.get("passed", True) else 1
        root = repository(project_root(args.root))
        with locked(root):
            cmd = args.command
            if cmd == "session":
                if args.session_command == "open":
                    output = Session.create(root, args.provider, knowledge).refresh()
                else:
                    session = Session(root, args.session_id, knowledge)
                    if args.session_command == "context":
                        output = session.refresh(args.goal)
                    else:
                        output = session.remember(read_json(args.input), args.observed)
                print(json.dumps(output, ensure_ascii=False, indent=2))
                return 0
            engine = Engine(root, args.goal, knowledge)
            if cmd == "init":
                output = engine.initialize(args.title, args.implementer, args.session, args.orchestrator, explicit_skill=args.explicit_skill)
            elif cmd in ("delegate", "team"):
                output = getattr(engine, cmd)(read_json(args.input), args.recover)
            elif cmd == "assess":
                output = engine.assess(read_json(args.input))
            elif cmd in ("status", "context"):
                output = engine.refresh()
            elif cmd == "validate":
                _, contract, discovery = engine.load()
                errors = validate(contract, discovery, root)
                output = {"passed": not errors, "errors": errors}
            elif cmd == "doctor":
                engine.load()
                output = providers.doctor(root, engine.state_dir / "doctor")
                output["passed"] = output["ok"]
            elif cmd == "plan-review":
                output = engine.plan_review()
            elif cmd == "checkpoint":
                output = engine.gate(args.milestone)
            elif cmd == "finish":
                output = engine.gate()
            elif cmd in ("block", "abort"):
                output = getattr(engine, cmd)(read_json(args.input) if cmd == "block" else args.reason)
            elif cmd == "retire":
                output = engine.retire(read_json(args.input))
            elif cmd == "note":
                output = engine.note(args.kind, args.text, args.evidence)
            else:
                output = getattr(engine, cmd)()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("passed", True) else 1
    except (LoopError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; inspect status and logs before resuming.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
