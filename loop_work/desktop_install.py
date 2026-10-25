"""Local macOS bundle compilation and exact manifest-owned file management."""
from __future__ import annotations
import hashlib
import errno
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from .storage import LoopError, digest, file_hash

SOURCE = Path(__file__).resolve().parents[1]
BUNDLE_FILES = ('Contents/Info.plist', 'Contents/MacOS/LoopWork', 'Contents/Resources/desktop-config.json')
BUNDLE_DIRS = ('Contents', 'Contents/MacOS', 'Contents/Resources')


def _safe(path):
    path=Path(path).absolute()
    for parent in [*reversed(path.parents),path]:
        if parent.is_symlink(): raise LoopError('Desktop path must not contain symbolic links: '+str(parent))
        if parent!=path and parent.exists() and not parent.is_dir(): raise LoopError('Desktop parent is not a directory: '+str(parent))
    return path


def configuration(entrypoint, knowledge_home=None, vault_home=None, project_id=None, target_root=None):
    def absolute(value):
        if value is None:return None
        value=Path(value).expanduser()
        if not value.is_absolute():raise LoopError('Desktop configuration paths must be absolute')
        return str(value)
    return {'version':1,'python':str(Path(sys.executable).resolve()),'entrypoint':absolute(entrypoint),
            'knowledge_home':absolute(knowledge_home),'vault_home':absolute(vault_home),
            'project_id':project_id,'target_root':absolute(target_root)}


def build_inputs(config):
    """Pin source/locks/toolchain; never install a global compiler or CLI."""
    from .desktop_sources import paths
    tools={name:shutil.which(name) for name in ('cargo','rustc','node','npm')}
    if any(value is None for value in tools.values()):
        raise LoopError('Tauri desktop requires existing cargo, rustc, node and npm; nothing was installed globally')
    versions={}
    for name,tool in tools.items():
        try:versions[name]=subprocess.run([tool,'--version'],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
        except (OSError,subprocess.SubprocessError) as exc:raise LoopError('Existing Tauri toolchain is unavailable') from exc
    required=('desktop/package.json','desktop/package-lock.json','desktop/src-tauri/Cargo.toml','desktop/src-tauri/Cargo.lock','desktop/src-tauri/src/main.rs')
    for name in required:
        if (SOURCE/name).is_symlink() or not (SOURCE/name).is_file():raise LoopError('Tauri source or lockfile is unavailable: '+name)
    return {'source_files':{p.relative_to(SOURCE).as_posix():file_hash(p) for p in paths(SOURCE)},
            'recipe_pins':{'installer':file_hash(Path(__file__)),'inventory':file_hash(Path(__file__).with_name('desktop_sources.py'))},
            'tools':tools,'versions':versions,'config':config,'platform':sys.platform,'machine':os.uname().machine}


def storage_observation(path, *, probe=False):
    """Observe capacity without inventing a cache-size threshold or deleting files."""
    selected=_safe(path)
    if selected.exists() and not selected.is_dir():
        raise LoopError('Native build directory is not a directory: '+str(selected))
    parent=selected
    while not parent.exists():parent=parent.parent
    if not parent.is_dir() or not os.access(parent,os.W_OK|os.X_OK):
        raise LoopError('Native build directory is not writable: '+str(selected))
    fd=None;temporary=None
    try:
        usage=shutil.disk_usage(parent)
        if probe:
            fd,temporary=tempfile.mkstemp(prefix='.loop-native-probe-',dir=parent)
            os.write(fd,b'0');os.fsync(fd)
        return {'path':str(selected),'observed_at_path':str(parent),'total_bytes':usage.total,
                'free_bytes':usage.free,'write_probe':bool(probe)}
    except OSError as exc:
        if exc.errno==errno.ENOSPC:raise LoopError('Native build storage has no space (ENOSPC): '+str(selected)) from exc
        raise LoopError('Native build storage is unavailable: '+str(selected)) from exc
    finally:
        if fd is not None:os.close(fd)
        if temporary is not None and os.path.exists(temporary):os.unlink(temporary)


def preflight_build(staging_path):
    # Keep changing free-space observations out of build_inputs' cache identity.
    return {'source':storage_observation(SOURCE/'desktop'),
            'destination':storage_observation(Path(staging_path).parent,probe=True)}


def build_failure(stage, exc):
    text=(getattr(exc,'stderr','') or '')
    if isinstance(text,bytes):text=text.decode('utf-8',errors='replace')
    no_space=isinstance(exc,OSError) and exc.errno==errno.ENOSPC or any(
        value in text.lower() for value in ('no space left on device','disk full','os error 28'))
    if no_space:
        original=text or str(exc)
        if len(original)>4000:
            marker='\n[diagnostic truncated]\n'
            original=original[:2000]+marker+original[-(2000-len(marker)):]
        error=LoopError('Tauri build storage exhausted (ENOSPC) during '+stage+'; existing files and caches were preserved: '+original);error.failure_kind='storage_enospc'
    elif isinstance(exc,subprocess.TimeoutExpired):
        error=LoopError('Tauri build timed out during '+stage+'; existing files and caches were preserved');error.failure_kind='timeout'
    else:
        error=LoopError('Tauri build failed before installation during '+stage+': '+(text or 'Local build command failed')[-4000:]);error.failure_kind='build_failed'
    return error


def build_app(staging_path, entrypoint:Path, knowledge_home:Path|None=None, vault_home:Path|None=None,
              project_id:str|None=None, *, target_root:Path|None=None, progress=None):
    if sys.platform!='darwin':raise LoopError('Tauri desktop bundles are currently verified on macOS only')
    config=configuration(entrypoint,knowledge_home,vault_home,project_id,target_root)
    app=_safe(staging_path)
    if app.exists():raise LoopError('Desktop staging destination already exists')
    preflight_build(app)
    inputs=build_inputs(config)
    frontend=SOURCE/'desktop';tools=inputs['tools']
    env={**os.environ,'CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS':'fallback'}
    commands=([tools['npm'],'ci','--no-audit','--no-fund'],[tools['npm'],'run','build'],
              [str(frontend/'node_modules/.bin/tauri'),'build','--no-bundle','--ci','--','--locked'])
    for stage,argv in zip(('npm_ci','frontend_build','shipping_tauri_build'),commands):
        if progress:progress(stage,'start')
        try:subprocess.run(argv,cwd=frontend,env=env,check=True,capture_output=True,text=True,timeout=900)
        except (OSError,subprocess.SubprocessError) as exc:
            if progress:progress(stage,'failed')
            raise build_failure(stage,exc) from exc
        if progress:progress(stage,'done')
    if progress:progress('bundle_packaging','start')
    binary=frontend/'src-tauri/target/release/loop-work-desktop'
    if binary.is_symlink() or not binary.is_file():raise LoopError('Tauri build did not produce the expected executable')
    # The executable embeds frontend assets. No development server or HTTP UI.
    for name in BUNDLE_DIRS:(app/name).mkdir(parents=True,exist_ok=True)
    plist={'CFBundleIdentifier':'org.loop-work.desktop','CFBundleName':'Loop Work','CFBundleDisplayName':'Loop Work',
           'CFBundleExecutable':'LoopWork','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'1.0',
           'NSHighResolutionCapable':True,'LSMinimumSystemVersion':'11.0','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(plist,sort_keys=True))
    (app/'Contents/Resources/desktop-config.json').write_text(json.dumps(config,ensure_ascii=False,sort_keys=True)+'\n')
    shutil.copyfile(binary,app/'Contents/MacOS/LoopWork');(app/'Contents/MacOS/LoopWork').chmod(0o755)
    if progress:progress('bundle_packaging','done')
    return app


def inspect_bundle(path):
    path=_safe(path)
    if not path.exists():return {}
    if not path.is_dir():raise LoopError('Desktop destination is not an application directory')
    result={}
    for parent,dirs,files in os.walk(path,followlinks=False):
        for name in dirs:
            item=Path(parent)/name;rel=item.relative_to(path).as_posix()
            if item.is_symlink() or rel not in BUNDLE_DIRS:raise LoopError('Unowned desktop directory preserved: '+rel)
        for name in files:
            item=Path(parent)/name;rel=item.relative_to(path).as_posix()
            if item.is_symlink() or not item.is_file() or rel not in BUNDLE_FILES:raise LoopError('Unowned desktop file preserved: '+rel)
            if rel == 'Contents/MacOS/LoopWork' and not os.access(item, os.X_OK):
                raise LoopError('Desktop executable permission changed; application preserved: '+str(item))
            result[rel]=file_hash(item)
    return result


def preflight(path, previous):
    current=inspect_bundle(path)
    if Path(path).exists() and previous is None:raise LoopError('Unowned desktop application preserved: '+str(path))
    if previous is not None and any(previous.get(name)!=pin for name,pin in current.items()):
        raise LoopError('User-modified desktop application preserved: '+str(path))
    return current


def publish(staged, destination, previous):
    staged=Path(staged);destination=_safe(destination)
    pins=inspect_bundle(staged)
    if set(pins)!=set(BUNDLE_FILES):raise LoopError('Native desktop bundle is incomplete')
    preflight(destination,previous)
    for name in BUNDLE_DIRS:(destination/name).mkdir(parents=True,exist_ok=True)
    for name in BUNDLE_FILES:
        target=_safe(destination/name);expected=(previous or {}).get(name)
        if target.exists() and file_hash(target)==pins[name]:continue
        if target.exists() and (expected is None or file_hash(target)!=expected):raise LoopError('Desktop file changed during installation; preserved')
        fd,temporary=tempfile.mkstemp(prefix='.loop-app-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write((staged/name).read_bytes());stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary,0o755 if name=='Contents/MacOS/LoopWork' else 0o644)
            if target.is_symlink() or target.exists() and (expected is None or file_hash(target)!=expected):raise LoopError('Desktop file changed during installation; preserved')
            if not target.exists():os.link(temporary,target)
            else:os.replace(temporary,target)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    return inspect_bundle(destination)


def remove(path, previous):
    path=_safe(path);preflight(path,previous)
    for name in BUNDLE_FILES:
        target=path/name
        if target.exists():
            if target.is_symlink() or file_hash(target)!=previous[name]:raise LoopError('Desktop changed during uninstall; preserved')
            target.unlink()
    for name in sorted(BUNDLE_DIRS,key=lambda n:n.count('/'),reverse=True):
        directory=path/name
        if directory.exists():directory.rmdir()
    if path.exists():path.rmdir()
