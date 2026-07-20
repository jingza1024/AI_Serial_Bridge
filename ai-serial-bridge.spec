# -*- mode: python ; coding: utf-8 -*-
"""
AI Serial Bridge 桌面应用打包配置 (PyInstaller, onedir)。

构建步骤：
  1. 先构建前端：  cd frontend && npm ci && npm run build
  2. 安装依赖：    pip install -r backend/requirements-desktop.txt pyinstaller
  3. 执行打包：    pyinstaller ai-serial-bridge.spec
  4. 产物目录：    dist/"AI Serial Bridge"/

仅打包桌面运行所需（FastAPI 后端 + pywebview），不含 MCP 服务端（mcp_server.py）
—— 桌面应用通过内置后端工作，MCP 由外部 AI 客户端独立启动。
"""

block_cipher = None

a = Analysis(
    ['desktop.py'],
    pathex=['.', 'backend'],
    binaries=[],
    datas=[
        # 前端构建产物作为只读资源打包
        ('frontend/dist', 'frontend/dist'),
    ],
    hiddenimports=[
        # 后端模块（desktop.py 经 sys.path 动态导入，需显式声明）
        'main',
        'automations',
        'serial_manager',
        'leases',
        'log_store',
        'transfers',
        'cryptography.fernet',
        'regex',
        # uvicorn 运行时按需加载的子模块
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # pyserial 工具
        'serial.tools.list_ports',
        # pywebview 平台后端（Windows: WinForms/pythonnet）
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 桌面应用不需要 MCP 与测试相关包，精简体积
        'mcp',
        'pytest',
    ],
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
    exclude_binaries=True,
    name='AI Serial Bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # 桌面 GUI：不显示控制台窗口。调试时改为 True 可查看 stdout/stderr。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/app.ico',  # 如有图标可取消注释
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI Serial Bridge',
)
