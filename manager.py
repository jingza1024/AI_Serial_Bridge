"""
AI Serial Bridge 服务管理器
支持 start / stop / restart / status
"""

import subprocess
import sys
import os
import time
import json
from pathlib import Path

# Windows 控制台 UTF-8 编码支持
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

PROJECT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_DIR / "backend"
FRONTEND_DIR = PROJECT_DIR / "frontend"
PID_FILE = PROJECT_DIR / ".pids.json"

BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _save_pids(pids: dict):
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(pids, f)


def _load_pids() -> dict:
    if not PID_FILE.exists():
        return {}
    with open(PID_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_process_running(pid: int) -> bool:
    """检查进程是否还在运行"""
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


def _find_process_by_port(port: int) -> int | None:
    """通过端口查找进程PID"""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"],
            capture_output=True, text=True, timeout=5
        )
        pid_str = result.stdout.strip()
        if pid_str and pid_str != "0":
            return int(pid_str)
    except Exception:
        pass
    return None


def _kill_process_tree(pid: int):
    """终止进程及其子进程"""
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=10
        )
    except Exception as e:
        print(f"  终止 PID {pid} 失败: {e}")


def _stop_by_pids():
    """通过PID文件停止服务"""
    pids = _load_pids()
    if not pids:
        return False

    stopped = False
    for name, pid in pids.items():
        if _is_process_running(pid):
            print(f"[STOP] 正在停止 {name} (PID: {pid})...")
            _kill_process_tree(pid)
            stopped = True
        else:
            print(f"[STOP] {name} (PID: {pid}) 已不在运行")
    
    PID_FILE.unlink(missing_ok=True)
    return stopped


def _stop_by_ports():
    """通过端口查找并停止服务"""
    stopped = False
    for port, name in [(BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")]:
        pid = _find_process_by_port(port)
        if pid:
            print(f"[STOP] 通过端口发现 {name} (PID: {pid}, port: {port})，正在终止...")
            _kill_process_tree(pid)
            stopped = True
    return stopped


def _stop_zombie_python():
    """清理遗留的 mcp_server.py 或 main.py Python 进程"""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -or $_.CommandLine -like '*mcp_server.py*' } | Select-Object ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.strip().split('\n') if l.strip() and 'ProcessId' not in l and '---' not in l]
        for line in lines:
            parts = line.split(None, 1)
            if parts and parts[0].isdigit():
                pid = int(parts[0])
                print(f"[STOP] 清理遗留 Python 进程 (PID: {pid})")
                _kill_process_tree(pid)
    except Exception:
        pass


def status():
    """查看服务状态"""
    pids = _load_pids()
    running = []
    
    # 检查PID文件中的进程
    for name, pid in pids.items():
        if _is_process_running(pid):
            running.append(name)
    
    # 检查端口
    for port, name in [(BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")]:
        pid = _find_process_by_port(port)
        if pid and name not in running:
            running.append(f"{name}(port:{port})")
    
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
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
    )
    pids["backend"] = backend_proc.pid
    
    # 等待后端就绪
    for i in range(20):
        time.sleep(0.5)
        if _find_process_by_port(BACKEND_PORT):
            print(f"[START] 后端已就绪 (PID: {backend_proc.pid}, port: {BACKEND_PORT})")
            break
    else:
        print(f"[WARN] 后端启动可能未完成，请检查")
    
    # 启动前端（stdout/stderr继承终端，stdin关闭）
    print("[START] 正在启动前端服务...")
    frontend_proc = subprocess.Popen(
        ["npx.cmd", "vite", "--host"],
        cwd=str(FRONTEND_DIR),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
    )
    pids["frontend"] = frontend_proc.pid
    
    # 等待前端就绪
    for i in range(20):
        time.sleep(0.5)
        if _find_process_by_port(FRONTEND_PORT):
            print(f"[START] 前端已就绪 (PID: {frontend_proc.pid}, port: {FRONTEND_PORT})")
            break
    else:
        print(f"[WARN] 前端启动可能未完成，请检查")
    
    _save_pids(pids)
    
    print()
    print("=" * 50)
    print("  AI Serial Bridge 所有服务已启动")
    print("=" * 50)
    print(f"  后端 API:   http://localhost:{BACKEND_PORT}")
    print(f"  前端界面:   http://localhost:{FRONTEND_PORT}")
    print(f"  MCP 配置:   C:\\Users\\{os.getlogin()}\\.kimi\\mcp.json")
    print()
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 50)
    print()
    
    # 主循环：占据终端，显示日志，等待 Ctrl+C
    try:
        while True:
            backend_alive = backend_proc.poll() is None
            frontend_alive = frontend_proc.poll() is None
            
            if not backend_alive:
                print("\n[WARN] 后端进程已退出")
                break
            
            if not frontend_alive:
                print("\n[WARN] 前端进程已退出")
                break
            
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 收到 Ctrl+C，正在停止服务...")
        _kill_process_tree(backend_proc.pid)
        _kill_process_tree(frontend_proc.pid)
        PID_FILE.unlink(missing_ok=True)
        print("[STOP] 所有服务已停止")
    
    return 0


def stop():
    """停止所有服务"""
    print("[STOP] 正在停止服务...")
    
    stopped = _stop_by_pids()
    if not stopped:
        stopped = _stop_by_ports()
    
    # 额外清理遗留进程
    _stop_zombie_python()
    
    PID_FILE.unlink(missing_ok=True)
    
    # 等待端口释放
    time.sleep(1)
    
    backend_pid = _find_process_by_port(BACKEND_PORT)
    frontend_pid = _find_process_by_port(FRONTEND_PORT)
    
    if backend_pid:
        print(f"[STOP] 后端仍在运行 (PID: {backend_pid})，强制终止...")
        _kill_process_tree(backend_pid)
    
    if frontend_pid:
        print(f"[STOP] 前端仍在运行 (PID: {frontend_pid})，强制终止...")
        _kill_process_tree(frontend_pid)
    
    print("[STOP] 所有服务已停止")
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
