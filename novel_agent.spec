# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for novel_agent GUI.
Build: pyinstaller novel_agent.spec
"""

a = Analysis(
    ['gui_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('novel_agent', 'novel_agent'),
        ('vendor', 'vendor'),
        ('config.py', '.'),
    ],
    hiddenimports=[
        'flet',
        'openai',
        'chromadb',
        'rank_bm25',
        'tiktoken',
        'novel_agent.gui',
        'novel_agent.gui.views',
        'novel_agent.gui.widgets',
        'novel_agent.gui.utils',
        'novel_agent.gui.controllers',
        'novel_agent.cli',
        'novel_agent.core',
        'novel_agent.agents',
        'novel_agent.llm',
        'novel_agent.project',
        'novel_agent.visualizer',
        'google.generativeai',
        'anthropic',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'matplotlib',
        'scipy',
        'pandas',
        'notebook',
        'jupyter',
        'IPython',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='novel_agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
