# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


block_cipher = None
project_root = Path(SPECPATH).resolve()
src_root = project_root / "src"
sys.path.insert(0, str(src_root))

hiddenimports = (
    collect_submodules("epub2pdf")
    + [
        "ebooklib",
        "ebooklib.epub",
        "fontTools.subset",
        "fontTools.ttLib",
        "fontTools.ttLib.ttCollection",
        "lxml.etree",
        "lxml.html",
        "pikepdf",
        "pikepdf._core",
        "pypdf",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "websocket",
    ]
)

datas = (
    collect_data_files("ebooklib")
    + collect_data_files("pikepdf")
)

binaries = (
    collect_dynamic_libs("shiboken6")
    + collect_dynamic_libs("PySide6")
)

pyside6_dir = Path(__import__("PySide6").__file__).resolve().parent
for dll in pyside6_dir.glob("*.dll"):
    binaries.append((str(dll), "PySide6"))

for src, dest in collect_dynamic_libs("shiboken6"):
    if Path(src).name.lower() == "shiboken6.abi3.dll":
        binaries.append((src, "PySide6"))

a = Analysis(
    [str(src_root / "epub2pdf" / "frozen_gui.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="EpubToPdf",
    debug=False,
    bootloader_ignore_signals=False,
    exclude_binaries=True,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon=str(project_root / "pixelapple.ico"),
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EpubToPdf",
)
