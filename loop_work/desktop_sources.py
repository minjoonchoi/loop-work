"""Bounded source inventory shared by copy, runtime seal and desktop build.

Generated dependencies, caches, frontend output and executables are never sources.
"""
from pathlib import Path
import os
from .storage import LoopError

TEXT_EXTENSIONS={'.rs','.toml','.lock','.json','.ts','.tsx','.js','.mjs','.cjs','.css','.html','.md','.txt','.svg'}
EXCLUDED={'node_modules','target','dist','.git','__pycache__','.vite','coverage','icons','gen','verification'}

def paths(source):
    root=Path(source)/'desktop'
    if not root.exists():return []
    result=[]
    for parent, dirs, files in os.walk(root,followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in dirs:
            if (Path(parent)/name).is_symlink():raise LoopError('Desktop source directory must not use symbolic links')
        for name in sorted(files):
            path=Path(parent)/name
            relative=path.relative_to(root)
            if path.is_symlink():raise LoopError('Desktop source must not use symbolic links: '+str(relative))
            if path.suffix not in TEXT_EXTENSIONS:continue
            if not path.is_file():raise LoopError('Desktop source must be a regular file: '+str(relative))
            if path.stat().st_size>32*1024*1024:raise LoopError('Desktop source exceeds bounded inventory size: '+str(relative))
            result.append(path)
    return sorted(result)
