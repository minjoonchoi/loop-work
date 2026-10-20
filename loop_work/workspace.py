"""Pure workspace paths and confined directory creation; no app/tool dependencies."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from .storage import LoopError

README = """# loop-work 지식 저장소

이 폴더는 loop-work의 단일 Obsidian vault입니다. Obsidian에서 **폴더를 vault로 열기**로
이 폴더를 선택하세요. 전역 vault 등록이나 플러그인 설정은 자동으로 변경하지 않습니다.
기존 사용자 노트와 .obsidian 설정은 보존합니다.

새 실행 데이터의 기본 위치는 옆의 ../data 폴더입니다. 기존 지식 저장소는 자동 이동하지
않습니다. loop-work를 제거해도 이 vault, 데이터와 Obsidian 앱은 보존합니다.

생성 문서는 SQLite/JSON 원본의 파생 보기입니다. 문서 내용만으로 승인·품질 검증·현재 완료
권한을 부여하지 않습니다. 사용자 메모는 notes 폴더에 별도로 작성할 수 있습니다.
"""


def _home(home=None):
    return Path(home).expanduser().resolve() if home is not None else Path.home().resolve()


def root(home=None):
    return _home(home) / ".loop-work"


def vault(home=None):
    return root(home) / "vault"


def data(home=None):
    return root(home) / "data"


def preflight(home=None):
    """Validate every bootstrap destination before any directory/app mutation."""
    base = _home(home)
    if not base.is_dir():
        raise LoopError("Workspace home directory does not exist: " + str(base))
    paths = (root(home), data(home), vault(home), vault(home) / ".obsidian")
    for path in paths:
        if path.is_symlink() or path.exists() and not path.is_dir():
            raise LoopError("Workspace directory conflicts with an existing file or symlink: " + str(path))
    note = vault(home) / "README.md"
    if note.is_symlink() or note.exists() and not note.is_file():
        raise LoopError("Workspace vault README conflicts with an existing directory or symlink: " + str(note))
    return {"root": str(root(home)), "vault": str(vault(home)), "data": str(data(home))}


def ensure(home=None):
    """Create only missing managed structure without following replaced links."""
    result = preflight(home)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    created = []
    try:
        with ExitStack() as opened:
            def child(parent, name, path):
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent)
                    created.append(str(path))
                except FileExistsError:
                    pass
                fd = os.open(name, flags, dir_fd=parent)
                opened.callback(os.close, fd)
                return fd
            base = os.open(str(_home(home)), flags)
            opened.callback(os.close, base)
            workspace = child(base, ".loop-work", root(home))
            child(workspace, "data", data(home))
            vault_fd = child(workspace, "vault", vault(home))
            child(vault_fd, ".obsidian", vault(home) / ".obsidian")
            try:
                fd = os.open("README.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=vault_fd)
            except FileExistsError:
                mode = os.stat("README.md", dir_fd=vault_fd, follow_symlinks=False).st_mode
                if not stat.S_ISREG(mode):
                    raise LoopError("Workspace README changed to a nonregular file; existing data preserved")
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(README)
                    stream.flush()
                    os.fsync(stream.fileno())
                created.append(str(vault(home) / "README.md"))
    except OSError as exc:
        raise LoopError("Workspace structure could not be created safely; existing notes were preserved: " + str(exc)) from exc
    return {**result, "created": created, "registered": False}
