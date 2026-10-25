"""Pure workspace paths and confined directory creation; no app/tool dependencies."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from .storage import LoopError

GUIDE = """# loop-work 지식 저장소 안내

프로젝트의 작업 결과와 재사용할 지식을 찾는 문서 공간입니다. 데스크톱 앱과 Obsidian은
같은 문서를 읽습니다. Obsidian에서 **폴더를 vault로 열기**로 이 폴더를 선택하세요.

## 문서 찾기

- `프로젝트/`에서 프로젝트 이름을 찾아 `목록.md`를 엽니다.
- 프로젝트의 `프로젝트 안내.md`는 사람이 정리하는 설명입니다.
- 프로젝트의 `지식/`에는 결정·설계·발견·회고처럼 다시 사용할 결론을 모읍니다.
- 프로젝트의 `작업/`에서 작업 이름을 찾아 `진행 현황.md`와 `작업 문서.md`를 엽니다.
- `공통 지식/`에는 여러 프로젝트에서 활용할 지식을, `개인 메모/`에는 직접 쓸 메모를 둡니다.

프로젝트·작업·지식 이름 끝의 짧은 식별자는 같은 이름을 구분합니다. `기록/중간/`과
`기록/완료/`는 당시 시점의 기록입니다. `기록/사용자 검토/`의 응답과 실제 실행은 별개입니다.

## 읽고 편집하기

지식 문서는 결론·활용 목적·확인한 내용·적용 범위와 한계·근거 순서로 읽습니다.
짧은 제목은 내용을 찾기 위한 이름이며 결론 전체를 대신하지 않습니다. 긴 원본 정보는
접힌 **원본 및 검증 정보**에서 확인합니다. 로컬 근거는 원래 파일이 있어야 열립니다.

`프로젝트 안내.md`와 `작업 문서.md`는 직접 편집할 수 있습니다. 생성된 진행 현황이나
검증 기록의 본문을 고쳐도 작업 완료·품질 검증·승인 권한이 생기지는 않습니다.
초안·가설·과거 성공과 현재 검증을 구분하고, 지식을 재사용하기 전에 최신성을 확인하세요.

## 데이터 보존

실행 데이터의 기본 위치는 옆의 `../data/`입니다. SQLite/개발 JSON은 실행·권한·검증의
원본이며 vault는 표시와 문서 공간입니다. 출력 오류가 실제 작업을 되돌리지는 않습니다.
기존 README·사용자 메모·`.obsidian` 설정은 보존하며 등록·플러그인·동기화 설정을 자동으로
변경하지 않습니다. 기존 지식 저장소는 자동 이동하지 않습니다. loop-work를 제거해도
vault·데이터·Obsidian 앱은 보존합니다.
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
    paths = (root(home), data(home), vault(home), vault(home) / ".obsidian", vault(home) / "개인 메모")
    for path in paths:
        if path.is_symlink() or path.exists() and not path.is_dir():
            raise LoopError("Workspace directory conflicts with an existing file or symlink: " + str(path))
    note = vault(home) / "안내.md"
    if note.is_symlink() or note.exists() and not note.is_file():
        raise LoopError("Workspace vault guide conflicts with an existing directory or symlink: " + str(note))
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
            child(vault_fd, "개인 메모", vault(home) / "개인 메모")
            try:
                fd = os.open("안내.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=vault_fd)
            except FileExistsError:
                mode = os.stat("안내.md", dir_fd=vault_fd, follow_symlinks=False).st_mode
                if not stat.S_ISREG(mode):
                    raise LoopError("Workspace guide changed to a nonregular file; existing data preserved")
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(GUIDE)
                    stream.flush()
                    os.fsync(stream.fileno())
                created.append(str(vault(home) / "안내.md"))
    except OSError as exc:
        raise LoopError("Workspace structure could not be created safely; existing notes were preserved: " + str(exc)) from exc
    return {**result, "created": created, "registered": False}
