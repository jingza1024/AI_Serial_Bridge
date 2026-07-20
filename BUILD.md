# 桌面应用打包指南

本文档说明如何将 AI Serial Bridge 打包为单机桌面应用（基于 PyInstaller + pywebview）。

## 前置条件

- Python 3.10+
- Node.js 20+ 与 npm
- Windows 10/11 与 Microsoft Edge WebView2 Runtime
- 当前 `ai-serial-bridge.spec` 面向 Windows WinForms；macOS/Linux 需要调整 pywebview 平台后端和 PyInstaller 配置
- 已安装完整打包依赖：

  ```bash
  python -m pip install -r backend/requirements-dev.txt
  ```

## 1. 构建前端

桌面模式由 FastAPI 直接托管 `frontend/dist`，因此必须先构建前端静态产物：

```bash
cd frontend
npm ci
npm run build          # 产物输出到 frontend/dist
cd ..
```

## 2. 执行打包

在项目根目录执行：

```bash
python -m PyInstaller ai-serial-bridge.spec
```

- 产物目录：`dist/AI Serial Bridge/`
- 可执行文件：`dist/AI Serial Bridge/AI Serial Bridge.exe`（Windows）

## 说明

- **仅打包桌面运行所需**：FastAPI 后端 + pywebview 前端壳。MCP 服务端（`mcp_server.py`）不在桌面包内——桌面应用通过内置后端工作，AI 客户端会单独启动 MCP 进程。
- **资源定位**：打包后 `desktop.py` 通过 `sys._MEIPASS` 定位内置的 `frontend/dist` 与后端模块，开发模式则定位源码目录。
- **调试控制台**：`ai-serial-bridge.spec` 中 `EXE(console=False)` 隐藏控制台窗口；调试启动问题时改为 `console=True` 可查看后端日志。
- **图标**：准备 `assets/app.ico` 后取消 spec 中 `icon=` 行的注释。
- **体积优化**：spec 中已排除 `mcp`、`pytest`。如需进一步瘦身可启用 UPX（spec 默认 `upx=True`，需系统已安装 UPX）。

## 开发模式（不打包）

无需打包时，直接运行：

```bash
python desktop.py
```

若 `frontend/dist` 不存在，开发模式会回退到 Vite 开发服务器（`http://localhost:5173`）；此时必须先在另一个终端执行 `cd frontend && npm run dev`，并确保后端端口 8000 可用。

## 访问鉴权

桌面应用未设置 `AI_SERIAL_TOKEN` 时，会在每次启动时自动生成随机 token，通过 URL fragment 交给前端换取 HttpOnly 会话；token 不会打印到日志或从 `/api/config` 返回。

如需固定 token，可在启动前显式设置：

设置环境变量后启动打包应用，后端将要求 token：

```powershell
# Windows (PowerShell)
$env:AI_SERIAL_TOKEN="your-random-secret"
& ".\AI Serial Bridge.exe"
```

固定 token 用于浏览器创建 HttpOnly 会话，也供外部 MCP 进程通过 Bearer 认证。连接同一桌面后端时，必须把相同的 `AI_SERIAL_TOKEN` 和实际 `AI_SERIAL_API_URL` 传给 MCP 进程。远程部署要求 TLS，并应阅读 `SECURITY.md`。
