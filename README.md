# AI Serial Bridge

让 AI Agent 直接使用串口的桥接工具，带 Web UI 实时监控。

## 功能

- **AI 直接控制串口**: 通过 MCP (Model Context Protocol) 协议，Claude Code / Cline / Continue / Kimi Code 等 Agent 可直接调用串口
- **Web UI 终端**: 基于 xterm.js 的终端界面，实时显示 AI 与设备的交互
- **交互模式**: 像 MobaXterm 一样直接在终端输入，支持 Tab 补全、方向键、Ctrl+C 等
- **用户干预**: 随时在 Web UI 中手动发送命令或打断 AI 操作
- **通信历史**: 完整记录串口收发日志，支持筛选查看

## 架构

```
AI Agent ──MCP/stdio──► mcp_server.py ──HTTP──► main.py ──USB──► 串口设备
                                              │
Web UI ──WebSocket──► main.py(FastAPI) ───────┘
```

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

### 3. 启动前端

```bash
cd frontend
npm run dev
```

访问: http://localhost:5173

## MCP 配置

MCP Server 通过 HTTP 代理到 main.py，与 Web UI 共享同一个串口状态。

### Kimi Code CLI

配置文件已创建在 `C:\Users\<你的用户名>\.kimi\mcp.json`：

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "E:/AI_Serial/backend/mcp_server.py"
      ]
    }
  }
}
```

重启 Kimi Code 会话后即可使用。

### Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "ai-serial-bridge": {
      "command": "python",
      "args": [
        "E:/AI_Serial/backend/mcp_server.py"
      ]
    }
  }
}
```

### Cline (VS Code)

在 Cline 的 MCP Settings 中添加 `mcp-config/cline_mcp_settings.json` 的内容。

### Continue (VS Code)

在 Continue 配置中添加 `mcp-config/continue_mcp_config.json` 的内容。

## 使用指南

### Web UI 操作

1. 打开浏览器访问 http://localhost:5173
2. 选择串口设备和波特率，点击「打开串口」
3. **交互模式**（默认）：直接在黑色终端区域点击并输入，像 MobaXterm 一样使用
   - Enter 发送命令
   - Tab 自动补全
   - 方向键浏览历史
   - Ctrl+C 中断当前程序
4. **命令模式**：在底部输入框输入命令发送
5. 观察终端中设备的返回数据

### AI Agent 操作

配置好 MCP 后，AI 会自动获得以下工具：

| 工具 | 说明 |
|------|------|
| `serial_list_ports` | 列出可用串口 |
| `serial_open` | 打开指定串口 |
| `serial_close` | 关闭串口 |
| `serial_write` | 发送数据（可指定换行符） |
| `serial_write_then_read` | 发送并等待响应 |
| `serial_get_history` | 获取通信历史 |

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
│   ├── mcp_server.py       # MCP Server (HTTP代理模式)
│   ├── serial_manager.py   # 串口管理器
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
├── mcp-config/
│   ├── claude_desktop_config.json
│   ├── cline_mcp_settings.json
│   └── continue_mcp_config.json
└── README.md
```

## 许可证

MIT
