# Contributing to AI Serial Bridge

Thank you for your interest in contributing to AI Serial Bridge! This document provides guidelines for contributing to the project.

## Development Setup

1. Fork and clone the repository
2. Install Python dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
3. Install Node.js dependencies:
   ```bash
   cd ../frontend
   npm install
   ```
4. Start the backend:
   ```bash
   cd ../backend
   python main.py
   ```
5. Start the frontend (in a new terminal):
   ```bash
   cd frontend
   npm run dev
   ```

## Coding Standards

- **Python**: Follow PEP 8 style guide
- **TypeScript/Vue**: Use the existing project conventions
- **No emoji in Python print statements** (to avoid encoding issues on Windows)
- Keep changes minimal and focused

## Testing Checklist

Before submitting a PR, please verify:

- [ ] Web UI can list, open, close serial ports
- [ ] Interactive mode (direct terminal input) works
- [ ] Command mode (input bar) works
- [ ] Multiple ports can be opened simultaneously
- [ ] MCP tools work with at least one AI Agent (Claude Desktop / Cursor / Cline / etc.)
- [ ] Closing a tab properly releases the serial port
- [ ] No console errors in browser dev tools

## Commit Messages

Use clear and descriptive commit messages. Examples:

- `feat: add support for new MCP tool serial_get_status`
- `fix: resolve port state sync issue between Web UI and MCP`
- `docs: update README with new agent configuration`

## Reporting Issues

When reporting bugs, please include:
- Your OS and Python/Node.js versions
- The AI Agent tool you're using (if MCP-related)
- Steps to reproduce
- Expected vs actual behavior
- Screenshots if applicable

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
