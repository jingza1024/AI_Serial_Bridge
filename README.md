# AI Serial Bridge

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Vue.js](https://img.shields.io/badge/Vue-3-green.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-1.0+-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**English** | [中文](README.zh-CN.md)

A bridge tool that lets AI Agents control serial ports directly, with a Web UI for real-time monitoring.

## Screenshots

**Web UI** - Real-time serial terminal with interactive & command modes  
![Web UI Terminal](assets/screenshots/webui-terminal.png)

**AI Agent** - Diagnosing network via serial port (ping + route)  
![AI Network Diagnosis](assets/screenshots/ai-network-diagnosis.png)

## Features

- **AI Direct Serial Control**: AI Agents (Claude, Cursor, Cline, Continue, Kimi Code, etc.) can directly call serial port tools via the Model Context Protocol (MCP)
- **Web UI Terminal**: xterm.js-based terminal interface that displays AI-device interactions in real time
- **Interactive Mode**: Click the terminal and type directly, just like MobaXterm. Supports Tab completion, arrow keys, Ctrl+C, and more
- **User Intervention**: Manually send commands or interrupt AI operations via the Web UI at any time
- **Communication History**: Complete RX/TX logs with filtering support
- **Multi-Tab**: Open multiple serial ports simultaneously, each with an independent terminal session

## Architecture

```
AI Agent --MCP/stdio--> mcp_server.py --HTTP--> main.py --USB--> Serial Device
                                              |
Web UI --WebSocket--> main.py(FastAPI) -------+
```

The MCP Server does not own serial hardware directly. Instead, it proxies to `main.py` via HTTP, sharing the same serial port state with the Web UI. Therefore, the backend service must be running before MCP can work.

## Quick Start (Recommended)

Use `manager.py` to manage all services with one command:

```bash
cd AI_Serial

# Start all services (backend + frontend)
python manager.py start

# Check status
python manager.py status

# Stop all services
python manager.py stop

# Restart all services
python manager.py restart
```

`start` occupies the current terminal (similar to `docker-compose up`), with backend and frontend logs interleaved. Press **Ctrl+C** once to gracefully stop all services.

After starting, visit: http://localhost:5173

## Manual Start

### 1. Install Dependencies

```bash
# Python backend
cd backend
pip install -r requirements.txt

# Node frontend
cd ../frontend
npm install
```

### 2. Start Backend

```bash
cd backend
python main.py
```

Backend runs at http://localhost:8000

### 3. Start Frontend

```bash
cd frontend
npm run dev
```

Visit: http://localhost:5173

## MCP Configuration

> **Prerequisite**: Ensure the backend service is running (`python main.py` or `python manager.py start`), because the MCP Server proxies to `localhost:8000` via HTTP.

All paths below are examples. Replace `<YOUR_PROJECT_PATH>` with your actual installation directory.

### Kimi Code CLI

> **Note**: The Kimi Code **VS Code Extension** does **not** support MCP. Only the **CLI version** does.

Config file: `~/.kimi/mcp.json` (Windows: `C:\Users\<username>\.kimi\mcp.json`)

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

Launch CLI with the config:

```bash
kimi --mcp-config-file C:\Users\<username>\.kimi\mcp.json
```

Reference: https://docs.moonshot.cn/kimi-cli/mcp

---

### Claude Desktop

Config file path:
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

**Fully quit and restart** Claude Desktop after saving.

Reference: https://modelcontextprotocol.io/quickstart/user

---

### Claude Code (CLI)

Add via CLI (recommended):

```bash
claude mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

Or manually edit `~/.claude/settings.json`:

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

Reference: https://github.com/anthropics/claude-code/blob/main/MCP.md

---

### Cursor

Config file path:
- **Global**: `~/.cursor/mcp.json`
- **Project-level**: `.cursor/mcp.json` (project root)

> Cursor requires an explicit `"type": "stdio"`.

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

After saving, confirm the server is loaded in Cursor Settings > MCP.

Reference: https://cursor.com/docs/mcp

---

### VS Code Built-in Copilot Chat (Agent Mode)

VS Code natively supports MCP for GitHub Copilot Chat Agent mode.

Config file path:
- **Workspace**: `.vscode/mcp.json` (recommended, can be version-controlled)
- **User**: Run command **MCP: Open User Configuration**

> VS Code uses `"servers"` as the top-level key (not `"mcpServers"`), and requires a `"type"` field.

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

After configuration, VS Code will prompt you to trust the server. Confirm to use it.

Reference: https://code.visualstudio.com/docs/copilot/customization/mcp-servers

---

### Cline (VS Code Extension)

Config file path:
- **Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
- **macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- **Linux**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

> If running Cline inside Cursor / Windsurf, replace `Code` with the corresponding editor name in the path.

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

You can also add it via the Cline panel: **MCP Servers** > **Configure MCP Servers**.

Reference: https://docs.cline.bot/mcp/adding-and-configuring-servers

---

### Continue.dev (VS Code / JetBrains)

Continue recommends the new **YAML configuration**:

Create `.continue/mcpServers/ai-serial-bridge.yaml` in your project root:

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

Or place it in `~/.continue/mcpServers/` for global availability.

Legacy JSON config (`~/.continue/config.json`) is still supported:

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

> **Note**: MCP tools only work in Continue's **Agent mode**. Regular Chat mode will not invoke tools.

Reference: https://docs.continue.dev/customize/deep-dives/mcp

---

### Windsurf (Codeium)

Config file: `~/.codeium/windsurf/mcp_config.json`

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

Reference: https://docs.windsurf.com/windsurf/cascade/mcp

---

### OpenCode

Config file path:
- **Global**: `~/.config/opencode/opencode.json`
- **Project-level**: `opencode.json` (project root, highest priority)

> OpenCode uses a different format: `"mcp"` is the top-level key, `"type": "local"` is required, and `"command"` is an **array**.

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

Reference: https://opencode.ai/docs/mcp-servers/

---

### Codex CLI (OpenAI)

Config file: `~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`)

> Codex uses TOML format. On Windows, WSL2 is recommended.

```toml
[mcp_servers.ai-serial-bridge]
command = "python"
args = ["<YOUR_PROJECT_PATH>/backend/mcp_server.py"]
```

Or add via CLI:

```bash
codex mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

Reference: https://developers.openai.com/codex/mcp

---

### Zed Editor

Config file:
- **macOS / Linux**: `~/.config/zed/settings.json`
- **Windows**: `%APPDATA%\Zed\settings.json`

> Zed uses `"context_servers"` (not `"mcpServers"`), with a nested command object.

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

Reference: https://zed.dev/docs/ai/mcp

## Usage Guide

### Web UI Operation

1. Open your browser and visit http://localhost:5173
2. Click **+** to select a serial port and baud rate, then click "Open Port"
3. **Interactive Mode** (default): Click the black terminal area and type directly, just like MobaXterm
   - Enter to send commands
   - Tab for auto-completion
   - Arrow keys for history
   - Ctrl+C to interrupt the current program
4. **Command Mode**: Type commands in the bottom input bar, with selectable newline mode (CR / LF / CRLF)
5. Observe the device response data in the terminal
6. Click **x** on a tab to close the port and release resources

### AI Agent Operation

Once MCP is configured, the AI automatically gains the following tools:

| Tool | Description | Parameters |
|------|-------------|------------|
| `serial_list_ports` | List available serial ports | None |
| `serial_open` | Open a specified serial port | `port` (required), `baudrate` |
| `serial_close` | Close a serial port | `port` (optional if single port) |
| `serial_write` | Send data to serial port | `data` (required), `port` (optional if single), `newline` |
| `serial_write_then_read` | Send and wait for response | `data` (required), `port` (optional if single), `wait_time` |
| `serial_get_history` | Get communication history | `port` (required), `limit` |
| `serial_is_open` | Check if a port is open | `port` (required) |

> **Note**: All operation tools (write/close/write_then_read) require a `port`. If only one port is open, the tool will auto-infer it. If multiple ports are open, you must explicitly pass the `port` parameter.

**Example conversation:**

> **User**: Turn on LED1  
> **AI**: Let me connect to the serial port and send the command...
> ```
> Use serial_open(port="COM3")
> Use serial_write(data="LED1 ON")
> ```
> Command sent, device returned: `OK\r\nLED1=ON`

## Tech Stack

- **Backend**: Python, FastAPI, pyserial, WebSocket
- **Frontend**: Vue 3, TypeScript, Vite, xterm.js
- **Agent Protocol**: Model Context Protocol (MCP)

## Project Structure

```
AI_Serial/
├── manager.py              # Service manager (start/stop/restart/status)
├── backend/
│   ├── main.py             # FastAPI + WebSocket service
│   ├── mcp_server.py       # MCP Server (stdio -> HTTP proxy)
│   ├── serial_manager.py   # Multi-port serial manager
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.vue
│       ├── components/
│       │   └── TerminalPanel.vue
│       ├── composables/
│       │   └── useSerial.ts
│       └── styles/
│           └── main.css
├── mcp-config/             # MCP config examples for each agent tool
│   ├── claude_desktop_config.json
│   ├── claude_code_settings.json
│   ├── cursor_mcp.json
│   ├── vscode_mcp.json
│   ├── cline_mcp_settings.json
│   ├── continue_mcp.yaml
│   ├── continue_mcp_config.json
│   ├── windsurf_mcp_config.json
│   ├── opencode_mcp.json
│   ├── codex_config.toml
│   └── zed_settings.json
├── assets/
│   └── screenshots/        # Project screenshots for README
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── README.zh-CN.md
```

## License

MIT
