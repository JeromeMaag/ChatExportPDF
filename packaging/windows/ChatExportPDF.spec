# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


def _collect_optional(package_name: str):
    try:
        return collect_all(package_name)
    except Exception:
        return [], [], []


spec_dir = Path(SPECPATH)
project_root = spec_dir.parents[1]
src_dir = project_root / "src"

datas = []
binaries = []
hiddenimports = []

for package in ("reportlab", "PIL", "emoji", "tzdata"):
    package_datas, package_binaries, package_hiddenimports = _collect_optional(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    [str(src_dir / "chat_export" / "gui_main.py")],
    pathex=[str(project_root), str(src_dir)],
    binaries=binaries,
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
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
    name="ChatExportPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
