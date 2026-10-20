"""Explicit, verified runtime copies; never install or rebind a session."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from .storage import LoopError, digest, engine_digest, file_hash


SOURCE = Path(__file__).resolve().parent.parent


def _directory(path):
    """Refuse symlinks at every existing lexical ancestor."""
    for part in [*reversed(path.parents), path]:
        try:
            mode = part.lstat().st_mode
        except FileNotFoundError as exc:
            raise LoopError('Runtime destination parent must already exist: ' + str(part)) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise LoopError('Runtime directory must be a real directory without symlink ancestors: ' + str(part))


def _inventory():
    paths = []
    for folder, pattern in (('loop_work', '*.py'), ('rules', '*.md'), ('templates', '*.json')):
        _directory(SOURCE / folder)
        selected = sorted((SOURCE / folder).glob(pattern))
        if not selected:
            raise LoopError('Missing runtime source files: ' + folder)
        paths.extend(selected)
    paths.extend(SOURCE / name for name in (
        'skills/loop-work/SKILL.md', 'skills/loop-work/agents/openai.yaml',
        'skills/loop-work/loop.py',
        'scripts/loop.py', 'scripts/runtime.py'))
    for folder in ('human_ui_assets', 'board_ui_assets'):
        paths.extend(SOURCE / 'loop_work' / folder / name
                     for name in ('index.html', 'app.js', 'style.css'))
    result = {}
    for path in paths:
        _directory(path.parent)
        if path.is_symlink() or not path.is_file():
            raise LoopError('Runtime source must be a regular non-symlink file: ' + str(path))
        result[path.relative_to(SOURCE).as_posix()] = file_hash(path)
    return result


def _sealed_engine(pins):
    # Keep exactly storage.harness_digest's canonical file set, not templates or
    # entry scripts: those are separately protected by the snapshot file pins.
    selected = {name: pin for name, pin in pins.items()
                if (name.startswith('loop_work/') and name.endswith('.py'))
                or (name.startswith('rules/') and name.endswith('.md'))
                or name.startswith('loop_work/human_ui_assets/')
                or name.startswith('loop_work/board_ui_assets/')
                or name in ('skills/loop-work/SKILL.md', 'skills/loop-work/agents/openai.yaml')}
    return digest({'version': 1, 'files': selected})


def _copy_files(source, destination, pins):
    for name in sorted(pins):
        original, target = source / name, destination / name
        _directory(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        _directory(target.parent)
        with original.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        target.chmod(stat.S_IMODE(original.stat().st_mode))
        if file_hash(target) != pins[name]:
            raise LoopError('Runtime copy differs from source pin: ' + name)


def _verify_copy(directory, pins, expected_engine):
    for name, pin in pins.items():
        path = directory / name
        if path.is_symlink() or file_hash(path) != pin:
            raise LoopError('Runtime copy pin mismatch: ' + name)
    code = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'from loop_work.storage import engine_digest; print(engine_digest())')
    result = subprocess.run([sys.executable, '-B', '-c', code, str(directory)],
                            cwd=directory, capture_output=True, text=True, timeout=30)
    if result.returncode or result.stdout.strip() != expected_engine:
        raise LoopError('Copied runtime engine digest does not match the executing source seal')


def snapshot(destination, expect_digest=None):
    """Create a new fixed runtime from this executing source; existing paths survive."""
    destination = Path(destination)
    if not destination.is_absolute() or '..' in destination.parts:
        raise LoopError('Use an absolute runtime destination without traversal')
    _directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise LoopError('Runtime destination already exists; preserve it and choose a new path')
    if expect_digest is not None and not re.fullmatch('[0-9a-f]{64}', expect_digest):
        raise LoopError('Expected engine digest must be a lowercase SHA-256 digest')
    pins = _inventory()
    sealed = _sealed_engine(pins)
    if engine_digest() != sealed:
        raise LoopError('Runtime source changed while sealing')
    if expect_digest is not None and sealed != expect_digest:
        raise LoopError('Executing runtime does not match the expected engine digest; no snapshot created')
    stage = Path(tempfile.mkdtemp(prefix='.loop-runtime-', dir=destination.parent))
    try:
        _copy_files(SOURCE, stage, pins)
        _verify_copy(stage, pins, sealed)
        if _inventory() != pins or engine_digest() != sealed:
            raise LoopError('Runtime source changed during snapshot; no snapshot published')
        # mkdir is the no-clobber reservation. rename(stage, destination) could
        # replace somebody else's newly created empty directory on POSIX.
        _directory(destination.parent)
        try:
            destination.mkdir()
        except FileExistsError as exc:
            raise LoopError('Runtime destination appeared during snapshot; preserved without replacement') from exc
        # Exclusive file creation also refuses a conflicting file introduced
        # after reservation. A failed publication remains for inspection.
        _copy_files(stage, destination, pins)
        _verify_copy(destination, pins, sealed)
        if _inventory() != pins or engine_digest() != sealed:
            raise LoopError('Runtime source changed before final verification; destination is unverified')
        manifest = {'version': 1, 'source': str(SOURCE), 'destination': str(destination),
                    'engine_digest': sealed, 'files': pins,
                    'entrypoint': str(destination / 'scripts/loop.py'),
                    'rules_home': str(destination / 'rules'),
                    'scope': 'Fixed runtime copy only; no installation, session rebinding or state resealing.'}
        with (destination / 'runtime-manifest.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        return {key: manifest[key] for key in ('destination', 'engine_digest', 'entrypoint', 'rules_home')} | {
            'manifest': str(destination / 'runtime-manifest.json')}
    except OSError as exc:
        raise LoopError('Runtime snapshot failed; preserve any destination for inspection: ' + str(exc)) from exc
    finally:
        shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('snapshot', help='Copy the executing runtime into a new absolute directory')
    create.add_argument('--destination', type=Path, required=True)
    create.add_argument('--expect-digest')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(snapshot(args.destination, args.expect_digest), ensure_ascii=False, indent=2))
        return 0
    except (LoopError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
