"""
AI Serial Bridge - Desktop Application
基于 PyWebView 的单窗口桌面应用
"""

import sys
import os
import secrets
import threading
import socket
import time
from urllib.parse import quote


def _get_base_dir():
    """获取资源基础目录，兼容开发模式与 PyInstaller 打包模式。

    打包后前端 dist 与后端模块都位于 PyInstaller 的解包目录 sys._MEIPASS 下。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller onedir/onefile 解包后的资源根目录
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _find_free_port(preferred: int = 8000) -> int:
    """尝试首选端口，失败则随机分配"""
    for port in [preferred, 0]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                if port == 0:
                    return s.getsockname()[1]
                return port
        except OSError:
            continue
    # 最终回退：让操作系统选择
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """阻塞等待 HTTP 服务器就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    base_dir = _get_base_dir()
    dist_dir = os.path.join(base_dir, 'frontend', 'dist')

    # 将 backend 目录加入 Python 路径
    backend_dir = os.path.join(base_dir, 'backend')
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    port = _find_free_port(8000)
    host = '127.0.0.1'
    if not os.path.isdir(dist_dir) and port != 8000:
        print("ERROR: 开发模式要求端口 8000 可用，因为 Vite 代理固定连接该端口")
        sys.exit(1)

    # 设置环境变量，让后端适配
    auth_token = os.environ.get('AI_SERIAL_TOKEN', '').strip() or secrets.token_urlsafe(32)
    os.environ['AI_SERIAL_TOKEN'] = auth_token
    os.environ['AI_SERIAL_PORT'] = str(port)
    os.environ['AI_SERIAL_HOST'] = host
    os.environ['AI_SERIAL_DESKTOP'] = '1'  # 标记：桌面模式

    # --- 在后台线程启动 FastAPI ---
    import uvicorn
    from main import app  # 路径与环境变量设置后再导入
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level='warning',
    ))

    def run_server():
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # --- 等待服务器就绪 ---
    print(f"[AI Serial Bridge] 正在启动服务 {host}:{port}...")
    if not _wait_for_server(host, port):
        print(f"ERROR: 后端服务启动失败 {host}:{port}")
        sys.exit(1)
    print(f"[AI Serial Bridge] 服务已就绪")

    # --- 打开 PyWebView 窗口 ---
    import webview

    if os.path.isdir(dist_dir):
        url = f'http://{host}:{port}/#token={quote(auth_token)}'
        print(f"[AI Serial Bridge] 加载前端: http://{host}:{port}/")
    else:
        # 开发回退：指向 Vite 开发服务器
        url = f'http://localhost:5173/#token={quote(auth_token)}'
        print("[AI Serial Bridge] 开发模式: http://localhost:5173/")

    window = webview.create_window(
        title='AI Serial Bridge',
        url=url,
        width=1200,
        height=800,
        min_size=(800, 600),
        text_select=True,
    )
    window.events.closed += lambda: setattr(server, 'should_exit', True)
    webview.start(debug=False)
    server.should_exit = True
    server_thread.join(timeout=5)


if __name__ == '__main__':
    main()
