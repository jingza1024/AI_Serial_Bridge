# AI Serial Bridge - 任务计划

## 目标
构建一个让 AI Agent 能直接使用串口的桥接软件，包含 Web UI 供用户监控和交互。

## 技术架构
- **后端**: Python + FastAPI + pyserial + WebSocket + MCP Server
- **前端**: Vue3 + Vite + TypeScript + xterm.js
- **协议**: MCP (Model Context Protocol) for AI Agent 集成

## 阶段

### Phase 1: 后端核心
- [x] 创建项目目录结构
- [ ] serial_manager.py - 串口管理器（打开/关闭/读写）
- [ ] mcp_server.py - MCP 协议服务器
- [ ] main.py - FastAPI 主程序（HTTP API + WebSocket）
- [ ] requirements.txt

### Phase 2: 前端界面
- [ ] Vite + Vue3 项目初始化配置
- [ ] useSerial.ts - WebSocket 串口交互 composable
- [ ] TerminalPanel.vue - xterm.js 终端组件
- [ ] App.vue - 主界面布局
- [ ] 样式和主题

### Phase 3: 配置与文档
- [ ] MCP 配置文件示例（Claude Desktop 等）
- [ ] README.md 使用说明
- [ ] 安装脚本

## 文件清单
```
ai-serial/
├── backend/
│   ├── main.py
│   ├── serial_manager.py
│   ├── mcp_server.py
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── components/
│       │   └── TerminalPanel.vue
│       ├── composables/
│       │   └── useSerial.ts
│       └── styles/
│           └── main.css
├── mcp-config/
│   └── claude_desktop_config.json
└── README.md
```
