# 桌面应用打包指南

本文档说明如何将 AI Serial Bridge 打包为单机桌面应用（基于 PyInstaller + pywebview）。

## 前置条件

- Python **3.10 - 3.14**（推荐 3.13）。超出该区间时，`PyYAML`、`pydantic-core`、`pythonnet` 等依赖可能没有预编译 wheel，pip 会回退到源码编译并要求安装 Visual C++ Build Tools。可用 `python scripts/check_python_version.py` 校验。
- Node.js 20+ 与 npm
- Windows 10/11 与 Microsoft Edge WebView2 Runtime
- 当前 `ai-serial-bridge.spec` 面向 Windows WinForms；macOS/Linux 需要调整 pywebview 平台后端和 PyInstaller 配置
- 已安装完整打包依赖：

  ```bash
  python -m pip install -r backend/requirements-build.txt
  ```

  `requirements-build.txt` 包含桌面运行依赖与 PyInstaller；只开发不打包时用 `backend/requirements-desktop.txt` 即可。依赖版本以 `backend/requirements.lock` 与 `backend/requirements-mcp.lock` 为准（`uv pip compile` 生成）。

## 1. 构建前端

桌面模式由 FastAPI 直接托管 `frontend/dist`，因此必须先构建前端静态产物：

```bash
cd frontend
npm ci
npm run build          # 产物输出到 frontend/dist
cd ..
```

## 2. 写入构建指纹

`desktop.py` 用内容指纹（而非文件时间戳）判断前端产物是否与源码一致。
构建完成后写入指纹：

```bash
python scripts/stamp_frontend_build.py
```

未写入指纹时回退到 mtime 比较；一旦存在 `.build-manifest.json`，源码变动而未重新构建会被明确拦截。

## 3. 执行打包

在项目根目录执行：

```bash
python -m PyInstaller ai-serial-bridge.spec
```

- 产物目录：`dist/AI Serial Bridge/`
- 可执行文件：`dist/AI Serial Bridge/AI Serial Bridge.exe`（Windows）

## 4. 验证产物（建议）

打包成功不代表可运行。用随附脚本做一次真实启动冒烟，它会校验后端就绪、首页可访问、静态资源可加载且未产生崩溃日志：

```bash
pwsh -File scripts/smoke_packaged_desktop.ps1
```

CI 中的 `desktop-package` job 执行等价的断言，因此**打包后白屏、资源路径错误这类回归会在合并前被拦截**。

## 说明

- **仅打包桌面运行所需**：FastAPI 后端 + pywebview 前端壳。MCP 服务端（`mcp_server.py`）不在桌面包内——桌面应用通过内置后端工作，AI 客户端会单独启动 MCP 进程。
- **资源定位**：前端产物随 `datas` 打进解包目录，onedir 布局下实际位置是 `dist/AI Serial Bridge/_internal/frontend/dist/`。`desktop.py` 与 `backend/frontend_assets.py` 会依次尝试 `sys._MEIPASS/frontend/dist`、可执行文件同级的 `_internal/frontend/dist`、同级 `frontend/dist`，以及源码模式下的仓库根。**不要假设资源就在 exe 旁边**——早期版本那样假设过，结果是窗口能打开但页面返回 `{"detail":"Not Found"}`。
- **资源缺失时的行为**：桌面模式找不到 `frontend/dist` 会立即中止启动，弹窗并写入 `crash.log`，其中会列出实际检查过的所有路径。
- **调试控制台**：`ai-serial-bridge.spec` 中 `EXE(console=False)` 隐藏控制台窗口；调试启动问题时改为 `console=True` 可查看后端日志。
- **图标**：准备 `assets/app.ico` 后取消 spec 中 `icon=` 行的注释。
- **体积优化**：spec 中已排除 `mcp`、`pytest`。如需进一步瘦身可启用 UPX（spec 默认 `upx=True`，需系统已安装 UPX）。
- **新增后端模块须加入 spec**：`desktop.py` 通过 `sys.path` 动态导入后端模块，PyInstaller 无法静态发现。新增模块时请同时加入 `ai-serial-bridge.spec` 的 `hiddenimports`，否则打包后的程序会在导入期失败。
- **MCP 版本**：MCP 代理当前依赖 `mcp>=1.0.0,<2.0.0`；桌面发行版不包含 MCP 代理，外部 MCP 客户端应在自己的虚拟环境中安装 `backend/requirements-mcp.txt`。

## 开发模式（不打包）

无需打包时，直接运行：

```bash
python desktop.py
```

也可以使用随附启动器，它们会固定使用项目 `.venv`：

```powershell
.\start_desktop.ps1            # 无控制台窗口
.\start_desktop.ps1 -Console   # 保留控制台查看后端日志
```

或双击 `start_desktop.bat`。

若 `frontend/dist` 不存在，开发模式会回退到 Vite 开发服务器（`http://localhost:5173`）；此时必须先在另一个终端执行 `cd frontend && npm run dev`，并确保后端端口 8000 可用（该端口来自 `backend/port_config.py`，可用 `AI_SERIAL_PORT` 覆盖，但 Vite 代理会随之读取同一变量）。

## 排查窗口一闪而过

打包程序以 `console=False` 运行时没有任何控制台输出，但启动日志会写入：

```
~/.ai-serial-bridge/logs/desktop.log      # 常规启动/运行日志（轮转）
~/.ai-serial-bridge/logs/crash.log        # Python 层未捕获异常（仅在真正崩溃时创建）
~/.ai-serial-bridge/logs/fault.log        # faulthandler 原生栈（段错误等硬崩溃）
```

其中 `crash.log` 的**存在本身就是崩溃信号**：正常启动不会创建该文件。`AI_SERIAL_STATE_DIR` 可重定位整个状态目录。

如果日志不足以定位，再临时将 spec 中的 `console=False` 改为 `console=True` 重新打包，从 PowerShell 启动查看完整输出，确认后恢复。

> `pythonw.exe`（无控制台解释器）下 `sys.stdout`/`sys.stderr` 为 `None`，任何调用 `isatty()` 的日志配置都会崩溃。`desktop.py` 已对此兜底，新增启动期代码时不要假设标准流一定存在。

## 访问鉴权

未设置 `AI_SERIAL_TOKEN` 时，桌面应用首次启动会创建 `~/.ai-serial-bridge/credentials.json`，后续启动复用同一用户级 token。token 仅通过 URL fragment 交给前端换取 HttpOnly 会话，不会打印到日志，也不会从 `/api/config` 或运行清单返回。

服务就绪后，桌面应用写入 `~/.ai-serial-bridge/runtime.json`，其中只包含回环 API URL、PID、启动时间和实例 ID。外部 MCP 代理每次请求都会重新读取凭据和运行清单，因此桌面端口变化无需手工同步。MCP 仍需在 AI 客户端中一次性注册，并与桌面使用同一 OS 账户；`AI_SERIAL_STATE_DIR` 仅用于该账户内重定位状态目录，不支持跨账户共享。

如需固定 token，可在启动前显式设置：

设置环境变量后启动打包应用，后端将要求 token：

```powershell
# Windows (PowerShell)
$env:AI_SERIAL_TOKEN="your-random-secret"
& ".\AI Serial Bridge.exe"
```

显式 token 不会替换保存的默认凭据。使用该覆盖值时，必须把相同的 `AI_SERIAL_TOKEN` 传给 MCP 进程；独立或远程后端还可显式设置 `AI_SERIAL_API_URL`。远程部署要求 TLS，并应阅读 `SECURITY.md`。
