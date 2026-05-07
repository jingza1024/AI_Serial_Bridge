# AI Serial Bridge

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Vue.js](https://img.shields.io/badge/Vue-3-green.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-1.0+-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**English** | [中文](README.zh-CN.md)

Give AI Agents hands to control the physical world through serial ports.

## What is AI Serial Bridge?

AI Serial Bridge is a **Model Context Protocol (MCP) server** that bridges AI coding assistants (Claude, Cursor, Cline, Continue, Kimi Code, etc.) with physical serial port devices. It turns your AI from a text-only assistant into a hardware-aware agent that can open serial ports, send commands, read device responses, and diagnose issues in real time.

Think of it as **MobaXterm with an AI brain** -- you get a familiar terminal interface for manual debugging, plus the ability to let AI autonomously interact with your hardware via natural language.

## The Problem

### 1. AI Cannot Touch Hardware
Traditional AI assistants operate purely in the digital realm -- they can write code, analyze logs, and suggest fixes, but they cannot physically interact with devices. When your embedded system crashes in the field, AI can only tell you *what might be wrong*, not *go check*.

### 2. Embedded Debugging is Tedious and Repetitive
Developers spend hours on repetitive serial port tasks:
- Manually connecting to COM ports with PuTTY / Tera Term
- Typing the same diagnostic commands over and over
- Copy-pasting device output into ChatGPT for analysis
- Switching between 5 tools just to debug one issue

### 3. Remote Device Maintenance is Painful
When a device is deployed on-site and you are in the office, debugging requires:
- VPN + remote desktop + serial-over-network tunnels
- Phone calls with on-site personnel reading hex dumps aloud
- Hours of back-and-forth just to run `ifconfig` or `dmesg`

### 4. No Standard Way for AI to Use Serial Ports
Every AI agent tool (Claude, Cursor, Cline...) has its own plugin system. There is no universal protocol for AI to control hardware. Each integration requires custom code.

## How AI Serial Bridge Solves It

| Before | After |
|--------|-------|
| AI suggests "check the serial logs" | AI **opens the serial port itself** and reads the logs |
| You type `ping www.baidu.com` manually | AI sends the command and **formats the results in a table** |
| Copy-paste hex dumps to ChatGPT | AI **analyzes device output in real time** via MCP |
| One person, one terminal, one device | **Multiple ports, AI + human collaboration**, Web UI for everyone |

### Key Design Decisions

- **MCP over stdio**: Works with any MCP-compatible AI agent -- no custom plugins needed
- **HTTP proxy architecture**: MCP Server does not own hardware directly; it proxies to a shared FastAPI backend, so Web UI and AI always see the same device state
- **WebSocket real-time sync**: When AI opens COM3 via MCP, the Web UI tab appears instantly. When you close a tab in the browser, the AI knows the port is gone.
- **Dual-mode terminal**: Interactive mode (direct keystroke forwarding like MobaXterm) for human control; Command mode (input bar) for scripted AI operations

## Use Cases

### Embedded Firmware Development
Flash firmware to STM32 / ESP32, read boot logs, adjust register values -- all via natural language. "Flash the new build to COM3 and tell me if the sensor initializes correctly."

### IoT Device Remote Diagnostics
Field-deployed Raspberry Pi or industrial gateway loses network. AI connects via serial, runs `ip route`, `dmesg`, and `systemctl status` to identify the root cause without anyone on-site.

### Industrial Automation (PLC / RTU)
Monitor Modbus/RS-485 connected PLCs. AI reads coil states, writes holding registers, and generates status reports automatically.

### Network Equipment Configuration
Configure routers, switches, and firewalls via their console ports. AI applies configuration templates, verifies connectivity with `ping`, and rolls back on failure.

### Hardware Testing & QA
Automate hardware-in-the-loop testing. AI sends test commands, validates responses against expected patterns, and generates pass/fail reports.

### Education & Prototyping
Students learn embedded systems by talking to their Arduino or Micro:bit in natural language. No need to remember AT command syntax.

## Features

- **AI Direct Serial Control**: Any MCP-compatible agent can list, open, write to, read from, and close serial ports via 7 standardized tools
- **Web UI Terminal**: xterm.js-based terminal with syntax highlighting, scrollback, and full ANSI support
- **Interactive Mode**: Click the terminal and type directly -- Tab completion, arrow keys, Ctrl+C interrupt, just like MobaXterm
- **Command Mode**: Bottom input bar with selectable newline modes (CR / LF / CRLF) for scripted operations
- **Local Echo Toggle**: Useful when the device does not echo back typed characters
- **AI Operation Logs**: Option to display AI-sent commands in the terminal with `[AI]` label for transparency
- **Multi-Tab Multi-Port**: Open COM3, COM4, and COM5 simultaneously -- each with an independent terminal session
- **Auto-Sync Between AI and Web UI**: AI opens a port -> tab appears in browser. You close a tab -> AI sees the port is gone
- **Communication History**: Full RX/TX logs per port with source attribution (User / AI / Device / System)
- **Anti-Fool Protection**: Prevents opening the same port twice; closing a tab automatically releases the serial resource
- **Service Manager**: One-command start/stop/restart for the entire stack (backend + frontend)

## Screenshots

**Web UI** - Real-time serial terminal with interactive & command modes  
![Web UI Terminal](assets/screenshots/webui-terminal.png)

**AI Agent** - Diagnosing network via serial port (ping + route)  
![AI Network Diagnosis](assets/screenshots/ai-network-diagnosis.png)

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
7. Toggle **EN** button in the header to switch the entire UI between English and Chinese

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
│   ├── locales.py          # Backend i18n (zh/en)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.vue
│       ├── components/
│       │   └── TerminalPanel.vue
│       ├── composables/
│       │   ├── useSerial.ts
│       │   └── useLocale.ts
│       ├── locales/
│       │   ├── zh.ts
│       │   └── en.ts
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
