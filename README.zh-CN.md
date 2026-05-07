# AI Serial Bridge

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Vue.js](https://img.shields.io/badge/Vue-3-green.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-1.0+-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | **中文**

让 AI Agent 拥有双手，直接控制物理世界中的串口设备。

## 什么是 AI Serial Bridge？

AI Serial Bridge 是一个基于 **Model Context Protocol (MCP)** 的桥接服务器，它将 AI 编程助手（Claude、Cursor、Cline、Continue、Kimi Code 等）与物理串口设备连接起来。它让你的 AI 从一个纯文本助手变成一个能够感知硬件的智能体——可以打开串口、发送命令、读取设备返回、实时诊断问题。

你可以把它理解为 **带 AI 大脑的 MobaXterm**——既保留了熟悉的终端界面供手动调试，又能让 AI 通过自然语言自主与硬件交互。

## 解决了什么问题？

### 1. AI 无法触碰物理硬件
传统的 AI 助手只能在数字世界运作——它们可以写代码、分析日志、给出修复建议，但无法与物理设备直接交互。当你的嵌入式系统在野外崩溃时，AI 只能告诉你*可能哪里出了问题*，却无法*亲自去检查*。

### 2. 嵌入式调试繁琐且重复
开发者每天花费大量时间在重复的串口操作上：
- 用 PuTTY / Tera Term 手动连接 COM 口
- 一遍又一遍地输入相同的诊断命令
- 把设备输出复制粘贴到 ChatGPT 里分析
- 为了调试一个问题要在 5 个工具之间来回切换

### 3. 远程设备维护困难重重
当设备部署在现场、而你在办公室时，调试意味着：
- VPN + 远程桌面 + 串口透传隧道的层层套娃
- 电话指挥现场人员逐字念十六进制转储
- 为了跑一个 `ifconfig` 或 `dmesg` 来回折腾数小时

### 4. 没有 AI 控制串口的标准方式
每个 AI 工具（Claude、Cursor、Cline...）都有自己的插件体系。没有通用协议让 AI 控制硬件，每次集成都要写定制代码。

## AI Serial Bridge 如何解决？

| 之前 | 之后 |
|------|------|
| AI 建议你"查看一下串口日志" | AI **自己打开串口**读取日志 |
| 你手动输入 `ping www.baidu.com` | AI 发送命令并**把结果整理成表格** |
| 复制粘贴十六进制转储到 ChatGPT | AI 通过 MCP **实时分析设备输出** |
| 一个人、一个终端、一台设备 | **多端口并行、AI + 人类协作**、Web UI 全员可见 |

### 核心设计决策

- **MCP stdio 传输**：兼容任何支持 MCP 的 AI 代理，无需定制插件
- **HTTP 代理架构**：MCP Server 不直接持有硬件，而是代理到共享的 FastAPI 后端，Web UI 和 AI 始终看到同一设备状态
- **WebSocket 实时同步**：AI 通过 MCP 打开 COM3，浏览器标签页立即出现；你在浏览器关闭标签，AI 立刻知道端口已释放
- **双模式终端**：交互模式（按键透传，像 MobaXterm 一样）供人工控制；命令模式（底部输入栏）供 AI 脚本化操作

## 应用场景

### 嵌入式固件开发
向 STM32 / ESP32 烧录固件、读取启动日志、调整寄存器值——全部用自然语言完成。"把新固件烧到 COM3，告诉我传感器是否正常初始化。"

### IoT 设备远程诊断
现场部署的树莓派或工业网关断网了。AI 通过串口连接，运行 `ip route`、`dmesg`、`systemctl status` 定位根因，无需任何人到现场。

### 工业自动化（PLC / RTU）
监控通过 Modbus/RS-485 连接的 PLC。AI 读取线圈状态、写入保持寄存器、自动生成状态报告。

### 网络设备配置
通过 Console 口配置路由器、交换机和防火墙。AI 应用配置模板、用 `ping` 验证连通性、失败时自动回滚。

### 硬件测试与 QA
自动化硬件在环测试。AI 发送测试命令、校验返回值是否符合预期、生成通过/失败报告。

### 教育与原型开发
学生用自然语言与 Arduino 或 Micro:bit 对话学习嵌入式系统，无需记忆 AT 指令语法。

## 功能

- **AI 直接控制串口**：任何 MCP 兼容代理都可以通过 7 个标准化工具列出、打开、写入、读取和关闭串口
- **Web UI 终端**：基于 xterm.js，支持语法高亮、滚动回溯、完整 ANSI 转义序列
- **交互模式**：点击终端直接输入——Tab 补全、方向键、Ctrl+C 中断，与 MobaXterm 体验一致
- **命令模式**：底部输入栏，支持选择换行符模式（CR / LF / CRLF），适合脚本化操作
- **本地回显开关**：设备不回显时开启，避免盲打
- **AI 操作日志**：可选在终端中显示 AI 发送的命令，带 `[AI]` 标签，全程透明
- **多标签多端口**：同时打开 COM3、COM4、COM5——每个端口独立终端会话
- **AI 与 Web UI 自动同步**：AI 打开端口 → 浏览器出现标签页；你关闭标签 → AI 知道端口已释放
- **通信历史**：每个端口的完整收发日志，标注来源（用户 / AI / 设备 / 系统）
- **防呆保护**：防止重复打开同一端口；关闭标签自动释放串口资源
- **服务管理器**：一键启动/停止/重启整个技术栈（后端 + 前端）

## 截图

**Web UI** - 实时串口终端，支持交互模式与命令模式  
![Web UI 终端](assets/screenshots/webui-terminal.png)

**AI Agent** - 通过串口进行网络诊断（ping + 路由）  
![AI 网络诊断](assets/screenshots/ai-network-diagnosis.png)

## 架构

```
AI Agent --MCP/stdio--> mcp_server.py --HTTP--> main.py --USB--> 串口设备
                                              |
Web UI --WebSocket--> main.py(FastAPI) -------+
```

MCP Server 不直接持有串口硬件，而是通过 HTTP 代理到 `main.py`，与 Web UI 共享同一个串口状态。因此必须先启动后端服务，MCP 才能正常工作。

## 快速开始（推荐）

使用 `manager.py` 一键管理所有服务：

```bash
# 进入项目目录
cd AI_Serial

# 启动所有服务（后端 + 前端）
python manager.py start

# 查看状态
python manager.py status

# 停止所有服务
python manager.py stop

# 重启所有服务
python manager.py restart
```

`start` 会占用当前终端（类似 `docker-compose up`），后台和前端的日志会交错输出。按 **Ctrl+C** 一次即可优雅停止所有服务。

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

后端运行在 http://localhost:8000

### 3. 启动前端

```bash
cd frontend
npm run dev
```

访问: http://localhost:5173

## MCP 配置

> **前提条件**: 确保后端服务已启动 (`python main.py` 或 `python manager.py start`)，因为 MCP Server 通过 HTTP 代理到 `localhost:8000`。

以下配置中所有路径均为示例，请将 `<YOUR_PROJECT_PATH>` 替换为你的实际安装目录。

### Kimi Code CLI

> **注意**: Kimi Code **VS Code 扩展**不支持 MCP，只有 **CLI 版本**支持。

配置文件: `~/.kimi/mcp.json` (Windows 路径: `C:\Users\<用户名>\.kimi\mcp.json`)

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

使用 CLI 启动时带上配置:

```bash
kimi --mcp-config-file C:\Users\<用户名>\.kimi\mcp.json
```

参考: https://docs.moonshot.cn/kimi-cli/mcp

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

保存后**完全退出并重启** Claude Desktop。

参考: https://modelcontextprotocol.io/quickstart/user

---

### Claude Code (CLI)

推荐通过 CLI 命令添加:

```bash
claude mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

或手动编辑配置文件 `~/.claude/settings.json`:

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

参考: https://github.com/anthropics/claude-code/blob/main/MCP.md

---

### Cursor

配置文件路径:
- **全局**: `~/.cursor/mcp.json`
- **项目级**: `.cursor/mcp.json` (项目根目录)

> Cursor 要求显式声明 `"type": "stdio"`。

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

保存后，在 Cursor 设置 > MCP 中确认服务器已加载。

参考: https://cursor.com/docs/mcp

---

### VS Code 内置 Copilot Chat (Agent 模式)

VS Code 原生支持 MCP，适用于 GitHub Copilot Chat Agent 模式。

配置文件路径:
- **工作区级**: `.vscode/mcp.json` (推荐，可纳入版本控制)
- **用户级**: 运行命令 **MCP: Open User Configuration**

> VS Code 使用 `"servers"` 作为顶层键（非 `"mcpServers"`），且必须包含 `"type"` 字段。

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

配置后 VS Code 会提示信任该服务器，确认后即可使用。

参考: https://code.visualstudio.com/docs/copilot/customization/mcp-servers

---

### Cline (VS Code Extension)

配置文件路径:
- **Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
- **macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- **Linux**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

> 如果在 Cursor / Windsurf 中运行 Cline，将路径中的 `Code` 替换为对应编辑器名称。

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

也可在 Cline 面板中点击 **MCP Servers** > **Configure MCP Servers** 通过 UI 添加。

参考: https://docs.cline.bot/mcp/adding-and-configuring-servers

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

或放入用户级目录 `~/.continue/mcpServers/` 实现全局可用。

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

> **注意**: MCP 工具仅在 Continue 的 **Agent 模式** 下可用，普通 Chat 模式不会调用工具。

参考: https://docs.continue.dev/customize/deep-dives/mcp

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

参考: https://docs.windsurf.com/windsurf/cascade/mcp

---

### OpenCode

配置文件路径:
- **全局**: `~/.config/opencode/opencode.json`
- **项目级**: `opencode.json` (项目根目录，优先级最高)

> OpenCode 的格式与其他工具不同：`"mcp"` 为顶层键，`"type": "local"` 为必需项，`"command"` 为**数组**。

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

参考: https://opencode.ai/docs/mcp-servers/

---

### Codex CLI (OpenAI)

配置文件: `~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`)

> Codex 使用 TOML 格式，Windows 上建议通过 WSL2 运行。

```toml
[mcp_servers.ai-serial-bridge]
command = "python"
args = ["<YOUR_PROJECT_PATH>/backend/mcp_server.py"]
```

或通过 CLI 添加:

```bash
codex mcp add ai-serial-bridge -- python <YOUR_PROJECT_PATH>/backend/mcp_server.py
```

参考: https://developers.openai.com/codex/mcp

---

### Zed Editor

配置文件:
- **macOS / Linux**: `~/.config/zed/settings.json`
- **Windows**: `%APPDATA%\Zed\settings.json`

> Zed 使用 `"context_servers"` 键（非 `"mcpServers"`），命令结构为嵌套对象。

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

参考: https://zed.dev/docs/ai/mcp

## 使用指南

### Web UI 操作

1. 打开浏览器访问 http://localhost:5173
2. 点击 **+** 选择串口设备和波特率，点击「打开串口」
3. **交互模式**（默认）：直接在黑色终端区域点击并输入，像 MobaXterm 一样使用
   - Enter 发送命令
   - Tab 自动补全
   - 方向键浏览历史
   - Ctrl+C 中断当前程序
4. **命令模式**：在底部输入框输入命令发送，可选择换行符模式（CR / LF / CRLF）
5. 观察终端中设备的返回数据
6. 点击标签页上的 **x** 关闭串口并释放资源
7. 点击 header 右上角的 **EN** 按钮可在中英文界面之间切换

### AI Agent 操作

配置好 MCP 后，AI 会自动获得以下工具：

| 工具 | 说明 | 参数 |
|------|------|------|
| `serial_list_ports` | 列出可用串口 | 无 |
| `serial_open` | 打开指定串口 | `port`(必填), `baudrate` |
| `serial_close` | 关闭指定串口 | `port`(单端口时可省略) |
| `serial_write` | 发送数据到串口 | `data`(必填), `port`(单端口时可省略), `newline` |
| `serial_write_then_read` | 发送并等待响应 | `data`(必填), `port`(单端口时可省略), `wait_time` |
| `serial_get_history` | 获取通信历史 | `port`(必填), `limit` |
| `serial_is_open` | 检查串口是否已打开 | `port`(必填) |

> **注意**: 所有涉及操作的工具（write/close/write_then_read）都需要指定 `port`。如果只打开了一个串口，工具会自动推断，无需手动指定。如果同时打开了多个串口，必须明确传入 `port` 参数。

**示例对话:**

> **用户**: 帮我把LED1打开  
> **AI**: 我先连接串口并发送命令...
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
├── manager.py              # 服务管理器 (start/stop/restart/status)
├── backend/
│   ├── main.py             # FastAPI + WebSocket 服务
│   ├── mcp_server.py       # MCP Server (stdio -> HTTP 代理)
│   ├── serial_manager.py   # 多串口管理器
│   ├── locales.py          # 后端国际化 (zh/en)
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
├── mcp-config/             # 各 Agent 工具的 MCP 配置示例
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
│   └── screenshots/        # 项目截图
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

## 许可证

MIT
