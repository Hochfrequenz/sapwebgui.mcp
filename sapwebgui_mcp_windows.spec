# -*- mode: python ; coding: utf-8 -*-
"""Canonical PyInstaller spec for the Windows .exe build.

Invoked by the CI job in ``.github/workflows/build_executable.yml`` and locally via
``uv run --group build_executable pyinstaller --noconfirm sapwebgui_mcp_windows.spec``.

Set ``SAPWEBGUI_BUILD_NAME`` to control the output filename (defaults to
``sapwebgui_mcp_windows``).
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# --- PyInstaller options needed by the dependencies ---
# - fastmcp uses importlib.metadata.version("fastmcp") at import time
# - fastmcp -> docket -> fakeredis needs commands.json data files
# - fastmcp -> docket -> fakeredis -> lupa needs Lua runtime submodules
# - sapwebguimcp ships js/, prompts/, data/, workflows/ non-Python files
# If fastmcp drops the docket dependency, the lupa/fakeredis lines can go.
datas = []
hiddenimports = []
datas += collect_data_files("fakeredis")
datas += collect_data_files("sapwebguimcp")
datas += copy_metadata("fastmcp")
hiddenimports += collect_submodules("lupa")

name = os.environ.get("SAPWEBGUI_BUILD_NAME", "sapwebgui_mcp_windows")

a = Analysis(
    ["src\\sapwebguimcp\\server.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
