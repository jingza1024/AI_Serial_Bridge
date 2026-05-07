# AI Serial Bridge

�?AI Agent 直接使用串口的桥接工具，�?Web UI 实时监控�?
## 功能

- **AI 直接控制串口**: 通过 MCP (Model Context Protocol) 协议，Claude / Cursor / Cline / Continue / Kimi Code �?Agent 可直接调用串口工�?- **Web UI 终端**: 基于 xterm.js 的终端界面，实时显示 AI 与设备的交互
- **交互模式**: �?MobaXterm 一样直接在终端输入，支�?Tab 补全、方向键、Ctrl+C �?- **用户干预**: 随时�?Web UI 中手动发送命令或打断 AI 操作
- **通信历史**: 完整记录串口收发日志，支持筛选查�?- **多标签页**: 同时打开多个串口，每个端口独立终端会�?
## 架构

```
AI Agent --MCP/stdio--> mcp_server.py --HTTP--> main.py --USB--> Serial Device
                                              |
Web UI --WebSocket--> main.py(FastAPI) -------+
```

MCP Server 不直接持有串口硬件，而是通过 HTTP 代理�?`main.py`，与 Web UI 共享同一个串口状态。因此必须先启动后端服务，MCP 才能正常工作�?
## 快速开始（推荐�?
使用 `manager.py` 一键管理所有服务：

```bash
# 进入项目目录
cd AI_Serial

# 启动所有服务（后端 + 前端�?python manager.py start

# 查看状�?python manager.py status

# 停止所有服�?python manager.py stop

# 重启所有服�?python manager.py restart
```

`start` 会占用当前终端（类似 `docker-compose up`），后台和前端的日志会交错输出。按 **Ctrl+C** 一次即可优雅停止所有服务�?
启动后访问：http://localhost:5173

## 手动启动

### 1. 安装依赖

```bash
# Python 后端
cd backend
pip install -r requirements.txt

# Node 前端
cd ../frontend
npm install
```

### 2. 启动后端

```bash
cd backend
python main.py
```

后端运行�?http://localhost:8000

### 3. 启动前端

```bash
cd frontend
npm run dev
```

访问: http://localhost:5173

## MCP 配置

> **前提条件**: 确保后端服务已启�?(`python main.py` �?`python manager.py start`)，因�?MCP Server 通过 HTTP 代理�?`localhost:8000`�?
以下配置中所有路径均为示例，请将 `<YOUR_PROJECT_PATH>` 替换为你的实际项目绝对路径�?
### Kimi Code CLI

> **注意**: Kimi Code **VS Code 扩展**不支�?MCP，只�?**CLI 版本**支持�?
配置文件: `~/.kimi/mcp.json` (Windows 路径: `C:\Users\<用户�?\.kimi\mcp.json`)

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

使用 CLI 启动时带上配�?

```bash
kimi --mcp-config-file C:\Users\<用户�?\.kimi\mcp.json
```

参�? https://docs.moonshot.cn/kimi-cli/mcp

---

### Claude Desktop

配置文件路径:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

保存�?*完全退出并重启** Claude Desktop�?
参�? https://modelcontextprotocol.io/quickstart/user

---

### Claude Code (CLI)

推荐通过 CLI 命令添加:

```bash
claude mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

或手动编辑配置文�?`~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

参�? https://github.com/anthropics/claude-code/blob/main/MCP.md

---

### Cursor

配置文件路径:
- **全局**: `~/.cursor/mcp.json`
- **项目�?*: `.cursor/mcp.json` (项目根目�?

> Cursor 要求显式声明 `"type": "stdio"`�?
```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "type": "stdio",
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

保存后，�?Cursor 设置 > MCP 中确认服务器已加载�?
参�? https://cursor.com/docs/mcp

---

### VS Code 内置 Copilot Chat (Agent 模式)

VS Code 原生支持 MCP，适用�?GitHub Copilot Chat Agent 模式�?
配置文件路径:
- **工作区级**: `.vscode/mcp.json` (推荐，可纳入版本控制)
- **用户�?*: 运行命令 **MCP: Open User Configuration**

> VS Code 使用 `"servers"` 作为顶层键（�?`"mcpServers"`），且必须包�?`"type"` 字段�?
```json
{
  "servers": {
    "ai-serial-bridge": {
      "type": "stdio",
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

配置�?VS Code 会提示信任该服务器，确认后即可使用�?
参�? https://code.visualstudio.com/docs/copilot/customization/mcp-servers

---

### Cline (VS Code Extension)

配置文件路径:
- **Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
- **macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- **Linux**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

> 如果�?Cursor / Windsurf 中运�?Cline，将路径中的 `Code` 替换为对应编辑器名称�?
```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ],
      "disabled": false,
      "alwaysAllow": []
    }
  }
}
```

也可�?Cline 面板中点�?**MCP Servers** > **Configure MCP Servers** 通过 UI 添加�?
参�? https://docs.cline.bot/mcp/adding-and-configuring-servers

---

### Continue.dev (VS Code / JetBrains)

Continue 新版推荐使用 **YAML 配置**:

在项目根目录创建 `.continue/mcpServers/ai-serial-bridge.yaml`:

```yaml
name: ai-serial-bridge
version: 0.0.1
schema: v1
mcpServers:
  - name: ai-serial-bridge
    type: stdio
    command: python
    args:
      - <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

或放入用户级目录 `~/.continue/mcpServers/` 实现全局可用�?
旧版 JSON 配置（`~/.continue/config.json`）仍兼容:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "python",
          "args": [
            "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
          ]
        }
      }
    ]
  }
}
```

> **注意**: MCP 工具仅在 Continue �?**Agent 模式** 下可用，普�?Chat 模式不会调用工具�?
参�? https://docs.continue.dev/customize/deep-dives/mcp

---

### Windsurf (Codeium)

配置文件: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

参�? https://docs.windsurf.com/windsurf/cascade/mcp

---

### OpenCode

配置文件路径:
- **全局**: `~/.config/opencode/opencode.json`
- **项目�?*: `opencode.json` (项目根目录，优先级最�?

> OpenCode 的格式与其他工具不同：`"mcp"` 为顶层键，`"type": "local"` 为必需项，`"command"` �?*数组**�?
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ai-serial-bridge": {
      "type": "local",
      "command": [
        "python",
        "<YOUR_PROJECT_PATH>/backend/mcp_server.py"
      ]
    }
  }
}
```

参�? https://opencode.ai/docs/mcp-servers/

---

### Codex CLI (OpenAI)

配置文件: `~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`)

> Codex 使用 TOML 格式，Windows 上建议通过 WSL2 运行�?
```toml
[mcp_servers.ai-serial-bridge]
command = "python"
args = ["<YOUR_PROJECT_PATH>/backend/mcp_server.py"]
```

或通过 CLI 添加:

```bash
codex mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

参�? https://developers.openai.com/codex/mcp

---

### Zed Editor

配置文件:
- **macOS / Linux**: `~/.config/zed/settings.json`
- **Windows**: `%APPDATA%\Zed\settings.json`

> Zed 使用 `"context_servers"` 键（�?`"mcpServers"`），命令结构为嵌套对象�?
```json
{
  "context_servers": {
    "ai-serial-bridge": {
      "command": {
        "path": "python",
        "args": ["<YOUR_PROJECT_PATH>/backend/mcp_server.py"],
        "env": {}
      }
    }
  }
}
```

参�? https://zed.dev/docs/ai/mcp

## 使用指南

### Web UI 操作

1. 打开浏览器访�?http://localhost:5173
2. 点击 **+** 选择串口设备和波特率，点击「打开串口�?3. **交互模式**（默认）：直接在黑色终端区域点击并输入，�?MobaXterm 一样使�?   - Enter 发送命�?   - Tab 自动补全
   - 方向键浏览历�?   - Ctrl+C 中断当前程序
4. **命令模式**：在底部输入框输入命令发送，可选择换行符模式（CR / LF / CRLF�?5. 观察终端中设备的返回数据
6. 点击标签页上�?**x** 关闭串口并释放资�?
### AI Agent 操作

配置�?MCP 后，AI 会自动获得以下工具：

| 工具 | 说明 | 参数 |
|------|------|------|
| `serial_list_ports` | 列出可用串口 | �?|
| `serial_open` | 打开指定串口 | `port`(必填), `baudrate` |
| `serial_close` | 关闭指定串口 | `port`(单端口时可省�? |
| `serial_write` | 发送数据到串口 | `data`(必填), `port`(单端口时可省�?, `newline` |
| `serial_write_then_read` | 发送并等待响应 | `data`(必填), `port`(单端口时可省�?, `wait_time` |
| `serial_get_history` | 获取通信历史 | `port`(必填), `limit` |
| `serial_is_open` | 检查串口是否已打开 | `port`(必填) |

> **注意**: 所有涉及操作的工具（write/close/write_then_read）都需要指�?`port`。如果只打开了一个串口，工具会自动推断，无需手动指定。如果同时打开了多个串口，必须明确传入 `port` 参数�?
**示例对话:**

> **用户**: 帮我把LED1打开  
> **AI**: 我先连接串口并发送命�?..
> ```
> 使用 serial_open(port="COM3")
> 使用 serial_write(data="LED1 ON")
> ```
> 已发送命令，设备返回: `OK\r\nLED1=ON`

## 技术栈

- **Backend**: Python, FastAPI, pyserial, WebSocket
- **Frontend**: Vue 3, TypeScript, Vite, xterm.js
- **Agent协议**: Model Context Protocol (MCP)

## 目录结构

```
AI_Serial/
├── manager.py              # 服务管理�?(start/stop/restart/status)
├── backend/
�?  ├── main.py             # FastAPI + WebSocket 服务
�?  ├── mcp_server.py       # MCP Server (stdio -> HTTP 代理)
�?  ├── serial_manager.py   # 多串口管理器
�?  └── requirements.txt
├── frontend/
�?  └── src/
�?      ├── App.vue
�?      ├── components/
�?      �?  └── TerminalPanel.vue
�?      ├── composables/
�?      �?  └── useSerial.ts
�?      └── styles/
�?          └── main.css
├── mcp-config/             # �?Agent 工具�?MCP 配置示例
�?  ├── claude_desktop_config.json
�?  ├── claude_code_settings.json
�?  ├── cursor_mcp.json
�?  ├── vscode_mcp.json
�?  ├── cline_mcp_settings.json
�?  ├── continue_mcp.yaml
�?  ├── continue_mcp_config.json
�?  ├── windsurf_mcp_config.json
�?  ├── opencode_mcp.json
�?  ├── codex_config.toml
�?  └── zed_settings.json
└── README.md
```

## 许可�?
MIT
