"""No shell interpolation, no interactive stdin, and bounded process groups."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time

from .storage import LoopError


class Cancelled(LoopError):
    """A task control interrupted execution; not a model-quality rejection."""


def execute(argv, cwd, log_dir, timeout, prompt=None, env_overrides=None, kill_tree=False, cancel=None):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    env = dict(os.environ, CI="true", GIT_TERMINAL_PROMPT="0", PIP_NO_INPUT="1")
    # Checks importing local Python modules must not create new source inventory
    # entries. Preserve an explicit host setting and per-call overrides.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.update(env_overrides or {})
    result = {"argv": argv, "exit_code": None, "timed_out": False,
              "cancelled": False, "stdout": str(log_dir / "stdout.log"), "stderr": str(log_dir / "stderr.log")}
    with (log_dir / "stdout.log").open("wb") as out, (log_dir / "stderr.log").open("wb") as err:
        try:
            reason=cancel() if cancel is not None else None
            if reason:
                result.update(cancelled=True,cancel_reason=str(reason),duration_seconds=round(time.monotonic()-started,3))
                return result
            process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                                       stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
                                       stdout=out, stderr=err)
            try:
                payload=prompt.encode() if prompt is not None else None
                if cancel is None:
                    process.communicate(payload,timeout=timeout)
                else:
                    deadline=time.monotonic()+timeout
                    while True:
                        reason=cancel()
                        if reason:
                            result.update(cancelled=True,cancel_reason=str(reason))
                            terminate(process,True)
                            break
                        remaining=deadline-time.monotonic()
                        if remaining<=0:
                            raise subprocess.TimeoutExpired(argv,timeout)
                        try:
                            process.communicate(payload,timeout=min(0.5,remaining))
                            reason=cancel()
                            if reason:
                                result.update(cancelled=True,cancel_reason=str(reason))
                                terminate(process,True)
                            break
                        except subprocess.TimeoutExpired:
                            payload=None
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                terminate(process, kill_tree)
            except BaseException:
                terminate(process, kill_tree)
                raise
            result["exit_code"] = process.returncode
        except OSError as exc:
            result["error"] = str(exc)
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def terminate(process, kill_tree=False):
    # Bench hosts can launch harness workers in their own process groups. Kill
    # observed descendants as well; never use provider-wide process-name matching.
    descendants = []
    if kill_tree:
        try:
            listing = subprocess.check_output(["ps", "-e", "-o", "pid=", "-o", "ppid="], timeout=5, text=True)
            parents = {int(pid): int(parent) for pid, parent in (line.split() for line in listing.splitlines())}
            owned = {process.pid}
            while True:
                more = {pid for pid, parent in parents.items() if parent in owned} - owned
                if not more:
                    break
                owned.update(more)
                descendants.extend(more)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    for pid in reversed(descendants):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # A child may still live even when its parent exits after SIGTERM.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()
