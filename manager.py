"""
AI Serial Bridge 服务管理器
支持 start / stop / restart / status
"""

import subprocess
import sys
import os
import signal
import time
import json
from pathlib import Path

# Windows 控制台 UTF-8 编码支持
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

IS_WINDOWS = sys.platform == "win32"
# Windows 下 npm 是 npm.cmd；POSIX 下直接用 npm
NPM_CMD = "npm.cmd" if IS_WINDOWS else "npm"


def _new_proc_group_kwargs() -> dict:
    """跨平台：将子进程放入独立进程组/会话，便于整组终止，并关闭 stdin。"""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP, "stdin": subprocess.DEVNULL}
    return {"start_new_session": True, "stdin": subprocess.DEVNULL}


PROJECT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_DIR / "backend"
FRONTEND_DIR = PROJECT_DIR / "frontend"
PID_FILE = PROJECT_DIR / ".pids.json"

BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _save_pids(pids: dict):
    temp_file = PID_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(pids, f)
    temp_file.replace(PID_FILE)


def _load_pids() -> dict:
    if not PID_FILE.exists():
        return {}
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_process_running(pid: int) -> bool:
    """检查进程是否还在运行"""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    # POSIX：os.kill(pid, 0) 不发送信号，仅做存在性检查
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程存在但无权限发信号
    except OSError:
        return False


def _find_process_by_port(port: int) -> int | None:
    """通过端口查找进程PID"""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"],
                capture_output=True, text=True, timeout=5
            )
            pid_str = result.stdout.strip()
            if pid_str and pid_str != "0":
                return int(pid_str)
        else:
            # POSIX：优先 lsof，回退 ss
            for cmd in (["lsof", "-ti", f":{port}"], ["ss", "-tlnpH"]):
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                except FileNotFoundError:
                    continue
                if cmd[0] == "lsof":
                    out = result.stdout.strip().splitlines()
                    if out and out[0].isdigit():
                        return int(out[0])
                else:  # ss
                    for line in result.stdout.splitlines():
                        if f":{port} " in line and "pid=" in line:
                            pid_part = line.split("pid=", 1)[1]
                            pid_str = "".join(c for c in pid_part if c.isdigit())
                            if pid_str:
                                return int(pid_str)
    except Exception:
        pass
    return None


def _get_process_command(pid: int) -> str:
    """读取进程命令行，仅用于验证 PID 是否属于本项目。"""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}").CommandLine',
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()

        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists():
            return proc_cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _process_matches(pid: int, expected_marker: str) -> bool:
    """确认 PID 命令行同时包含项目目录和预期入口，避免误杀。"""
    command = _get_process_command(pid)
    if not command:
        return False
    normalized = command.replace("\\", "/").lower()
    project = str(PROJECT_DIR).replace("\\", "/").lower()
    marker = expected_marker.replace("\\", "/").lower()
    if project in normalized and marker in normalized:
        return True
    # npm.cmd 通常会转为 node + npm-cli.js，命令行不一定包含 cwd；PID 文件仍提供首要边界。
    return marker == "run dev" and "run dev" in normalized and ("npm" in normalized or "vite" in normalized)


def _kill_process_tree(pid: int):
    """终止进程及其子进程"""
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10
            )
        else:
            # 先递归终止子进程，再终止父进程；先 SIGTERM 后 SIGKILL
            try:
                res = subprocess.run(
                    ["pgrep", "-P", str(pid)],
                    capture_output=True, text=True, timeout=5
                )
                child_pids = [int(x) for x in res.stdout.split() if x.isdigit()]
            except (FileNotFoundError, Exception):
                child_pids = []
            for cpid in child_pids:
                _kill_process_tree(cpid)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    return
                except Exception:
                    break
                time.sleep(0.2)
                if not _is_process_running(pid):
                    return
    except Exception as e:
        print(f"  终止 PID {pid} 失败: {e}")


def _stop_by_pids():
    """通过PID文件停止服务"""
    pids = _load_pids()
    if not pids:
        return False

    stopped = False
    for name, record in pids.items():
        if isinstance(record, dict):
            pid = int(record.get("pid", 0))
            marker = str(record.get("command", ""))
        else:
            pid = int(record)
            marker = str(BACKEND_DIR / "main.py") if name == "backend" else "npm"
        if _is_process_running(pid):
            if marker and _process_matches(pid, marker):
                print(f"[STOP] 正在停止 {name} (PID: {pid})...")
                _kill_process_tree(pid)
                stopped = True
            else:
                print(f"[WARN] 拒绝终止未通过身份校验的 {name} (PID: {pid})")
        else:
            print(f"[STOP] {name} (PID: {pid}) 已不在运行")
    
    PID_FILE.unlink(missing_ok=True)
    return stopped


def status():
    """查看服务状态"""
    pids = _load_pids()
    running = []
    
    # 检查PID文件中的进程
    for name, record in pids.items():
        pid = int(record.get("pid", 0)) if isinstance(record, dict) else int(record)
        marker = str(record.get("command", "")) if isinstance(record, dict) else name
        if _is_process_running(pid) and _process_matches(pid, marker):
            running.append(name)
    
    # 检查端口
    for port, name in [(BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")]:
        pid = _find_process_by_port(port)
        if pid and name not in running:
            running.append(f"端口占用(非托管):{port}/PID:{pid}")
    
    if running:
        print(f"[STATUS] 运行中: {', '.join(running)}")
    else:
        print("[STATUS] 未运行")
    return 0


def start():
    """启动所有服务"""
    # 先检查是否已有服务在运行
    if _find_process_by_port(BACKEND_PORT) or _find_process_by_port(FRONTEND_PORT):
        print("[WARN] 检测到已有服务在运行，请先执行 stop")
        status()
        return 1
    
    pids = {}
    
    # 启动后端（stdout/stderr继承终端显示日志，stdin关闭防止抢占键盘）
    print("[START] 正在启动后端服务...")
    backend_proc = subprocess.Popen(
        [sys.executable, str(BACKEND_DIR / "main.py")],
        cwd=str(BACKEND_DIR),
        **_new_proc_group_kwargs(),
    )
    pids["backend"] = {
        "pid": backend_proc.pid,
        "command": str(BACKEND_DIR / "main.py"),
    }
    _save_pids(pids)
    
    # 等待后端就绪
    for i in range(20):
        time.sleep(0.5)
        if _find_process_by_port(BACKEND_PORT):
            print(f"[START] 后端已就绪 (PID: {backend_proc.pid}, port: {BACKEND_PORT})")
            break
    else:
        print("[ERROR] 后端未在规定时间内就绪")
        _kill_process_tree(backend_proc.pid)
        PID_FILE.unlink(missing_ok=True)
        return 1
    
    # 启动前端（stdout/stderr继承终端，stdin关闭）
    print("[START] 正在启动前端服务...")
    frontend_proc = subprocess.Popen(
        [NPM_CMD, "run", "dev"],
        cwd=str(FRONTEND_DIR),
        **_new_proc_group_kwargs(),
    )
    pids["frontend"] = {
        "pid": frontend_proc.pid,
        "command": "run dev",
    }
    _save_pids(pids)
    
    # 等待前端就绪
    for i in range(20):
        time.sleep(0.5)
        if _find_process_by_port(FRONTEND_PORT):
            print(f"[START] 前端已就绪 (PID: {frontend_proc.pid}, port: {FRONTEND_PORT})")
            break
    else:
        print("[ERROR] 前端未在规定时间内就绪")
        _kill_process_tree(frontend_proc.pid)
        _kill_process_tree(backend_proc.pid)
        PID_FILE.unlink(missing_ok=True)
        return 1
    
    print()
    print("=" * 50)
    print("  AI Serial Bridge 所有服务已启动")
    print("=" * 50)
    print(f"  后端 API:   http://localhost:{BACKEND_PORT}")
    print(f"  前端界面:   http://localhost:{FRONTEND_PORT}")
    if IS_WINDOWS:
        print(f"  MCP 配置:   C:\\Users\\{os.getlogin()}\\.kimi\\mcp.json")
    else:
        print(f"  MCP 配置:   ~/.kimi/mcp.json")
    print()
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 50)
    print()
    
    # 主循环：占据终端，显示日志，等待 Ctrl+C
    exit_code = 0
    try:
        while True:
            backend_alive = backend_proc.poll() is None
            frontend_alive = frontend_proc.poll() is None
            
            if not backend_alive:
                print("\n[WARN] 后端进程已退出")
                exit_code = 1
                break
            
            if not frontend_alive:
                print("\n[WARN] 前端进程已退出")
                exit_code = 1
                break
            
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 收到 Ctrl+C，正在停止服务...")
    finally:
        if backend_proc.poll() is None:
            _kill_process_tree(backend_proc.pid)
        if frontend_proc.poll() is None:
            _kill_process_tree(frontend_proc.pid)
        PID_FILE.unlink(missing_ok=True)
        print("[STOP] 所有服务已停止")

    return exit_code


def stop():
    """停止所有服务"""
    print("[STOP] 正在停止服务...")
    
    stopped = _stop_by_pids()
    PID_FILE.unlink(missing_ok=True)
    
    # 等待端口释放
    time.sleep(1)
    
    backend_pid = _find_process_by_port(BACKEND_PORT)
    frontend_pid = _find_process_by_port(FRONTEND_PORT)
    
    if backend_pid:
        print(f"[WARN] 端口 {BACKEND_PORT} 仍被 PID {backend_pid} 占用；未强制终止非托管进程")
    if frontend_pid:
        print(f"[WARN] 端口 {FRONTEND_PORT} 仍被 PID {frontend_pid} 占用；未强制终止非托管进程")

    print("[STOP] 托管服务已停止" if stopped else "[STOP] 未发现可安全停止的托管服务")
    return 0


def restart():
    """重启所有服务"""
    stop()
    time.sleep(1)
    return start()


def main():
    if len(sys.argv) < 2:
        cmd = "status"
    else:
        cmd = sys.argv[1].lower()
    
    if cmd == "start":
        sys.exit(start())
    elif cmd == "stop":
        sys.exit(stop())
    elif cmd == "restart":
        sys.exit(restart())
    elif cmd == "status":
        sys.exit(status())
    else:
        print(f"未知命令: {cmd}")
        print("用法: python manager.py [start|stop|restart|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
