"""
AI Serial Bridge - Desktop Application
基于 PyWebView 的单窗口桌面应用
"""

import sys
import os
import json
import threading
import socket
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener


# 防止重复进入 venv 重定向的标记
_VENV_REEXEC_ENV = "AI_SERIAL_VENV_REEXEC"

# 桌面版最低依赖（缺失时自动切换到 .venv）
_REQUIRED_MODULES = ("uvicorn", "webview", "fastapi")


def _ensure_std_streams() -> None:
    """保证 sys.stdout / sys.stderr 可用。

    pythonw.exe 启动的 GUI 进程没有控制台，两者为 None；任何调用
    ``sys.stdout.isatty()`` 的日志配置（如 uvicorn）都会因此崩溃。
    """
    import io

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None:
            continue
        try:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", buffering=1))
        except OSError:
            setattr(sys, name, io.StringIO())


def _venv_python(base_dir: Path) -> Path | None:
    """返回项目内 .venv 的解释器路径（若存在）。"""
    if os.name == "nt":
        candidate = base_dir / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = base_dir / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def _missing_runtime_dependencies() -> list[str]:
    """返回当前解释器缺失的关键运行时依赖。

    无法判定时（例如测试中注入了模块桩、``__spec__`` 缺失）按"可用"处理，
    避免误触发解释器重定向。
    """
    import importlib.util

    missing = []
    for name in _REQUIRED_MODULES:
        if name in sys.modules:
            continue
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            found = True
        if not found:
            missing.append(name)
    return missing


def _ensure_venv_interpreter() -> None:
    """当前解释器缺少依赖时，自动切换到项目 .venv 后重新启动。

    这样无论用户用哪个 `python`（例如 PATH 上更靠前的系统 Python）启动，
    都能进入依赖完整的虚拟环境，而不是抛出 ModuleNotFoundError。
    """
    # 打包后已固化解释器与依赖，无需切换
    if getattr(sys, "frozen", False):
        return
    # 已经在重定向过程中，避免递归
    if os.environ.get(_VENV_REEXEC_ENV) == "1":
        return

    missing = _missing_runtime_dependencies()
    if not missing:
        return

    base_dir = Path(__file__).resolve().parent
    venv_python = _venv_python(base_dir)
    if venv_python is None:
        print(f"ERROR: 当前 Python 缺少依赖: {', '.join(missing)}")
        print(f"       且未找到虚拟环境 {base_dir / '.venv'}")
        print("       请先创建并安装依赖：")
        print("         py -3.13 -m venv .venv")
        print("         .venv\\Scripts\\python.exe -m pip install -r backend\\requirements-desktop.txt")
        raise SystemExit(1)

    # 同一解释器就不必重定向（例如 venv 自身依赖损坏时避免死循环）
    try:
        same = os.path.samefile(sys.executable, venv_python)
    except OSError:
        same = False
    if same:
        print(f"ERROR: 虚拟环境 {venv_python} 中依赖不完整：{', '.join(missing)}")
        print("       请重新安装：.venv\\Scripts\\python.exe -m pip install -r backend\\requirements-desktop.txt")
        raise SystemExit(1)

    print(f"[AI Serial Bridge] 当前解释器缺少 {', '.join(missing)}，"
          f"自动切换到项目虚拟环境：{venv_python}")

    import subprocess

    env = os.environ.copy()
    env[_VENV_REEXEC_ENV] = "1"
    # 用 venv 解释器重新执行本脚本，保留全部命令行参数
    completed = subprocess.run(
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        env=env,
        cwd=str(base_dir),
    )
    raise SystemExit(completed.returncode)


_DIRECT_OPENER = build_opener(ProxyHandler({}))


def _open_loopback_url(request: Request, timeout: float):
    return _DIRECT_OPENER.open(request, timeout=timeout)


def _get_base_dir() -> Path:
    """获取资源基础目录，兼容开发模式与 PyInstaller 打包模式。

    打包后前端 dist 与后端模块都位于 PyInstaller 的解包目录 sys._MEIPASS 下。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller onedir/onefile 解包后的资源根目录
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _frontend_build_is_stale(base_dir: Path) -> bool:
    """判断前端产物是否落后于源码。

    优先使用构建指纹（.build-manifest.json），无指纹时回退 mtime，
    详见 backend/build_manifest.py。
    """
    frontend_dir = base_dir / 'frontend'
    if not (frontend_dir / 'dist' / 'index.html').is_file():
        return False
    backend_dir = base_dir / 'backend'
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    try:
        import build_manifest
    except ImportError:
        # 极端情况下（打包/裁剪）退回时间戳比较
        return _mtime_stale(frontend_dir)
    return build_manifest.bundle_is_stale(frontend_dir)


def _mtime_stale(frontend_dir: Path) -> bool:
    """回退路径：比较源文件与入口页的 mtime。"""
    bundle_index = frontend_dir / 'dist' / 'index.html'
    inputs = [path for path in (frontend_dir / 'src').rglob('*') if path.is_file()]
    inputs.extend(
        path for path in (
            frontend_dir / 'index.html',
            frontend_dir / 'package.json',
            frontend_dir / 'package-lock.json',
            frontend_dir / 'tsconfig.json',
            frontend_dir / 'vite.config.ts',
        ) if path.is_file()
    )
    try:
        return bool(inputs) and max(p.stat().st_mtime for p in inputs) > bundle_index.stat().st_mtime
    except OSError:
        return False


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


def _wait_for_server(
    host: str,
    port: int,
    instance_id: str,
    timeout: float = 10.0,
) -> bool:
    """Wait until this desktop instance answers the public config endpoint."""
    deadline = time.monotonic() + timeout
    config_url = f'http://{host}:{port}/api/config'
    while time.monotonic() < deadline:
        try:
            request = Request(config_url, method='GET')
            with _open_loopback_url(request, timeout=0.5) as response:
                payload = json.loads(response.read().decode('utf-8'))
            if (
                isinstance(payload, dict)
                and payload.get('service') == 'ai-serial-bridge'
                and payload.get('instance_id') == instance_id
            ):
                return True
        except (OSError, UnicodeDecodeError, ValueError):
            pass
        time.sleep(0.1)
    return False


def _resolve_bundle_dir(base_dir: Path) -> Path | None:
    """定位前端构建产物目录。

    以传入的 base_dir 为准（源码模式即仓库根，打包模式即 sys._MEIPASS），
    这样测试可以注入任意目录，而不依赖调用时解释器的真实布局。
    """
    candidates = [base_dir / 'frontend' / 'dist']
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.insert(0, Path(meipass) / 'frontend' / 'dist')
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / '_internal' / 'frontend' / 'dist',
            exe_dir / 'frontend' / 'dist',
        ])

    for candidate in candidates:
        try:
            if (candidate / 'index.html').is_file():
                return candidate
        except OSError:
            continue
    return None


def _report_startup_failure(detail: str, title: str) -> None:
    """把启动失败报告给用户，并保证进程能够正常退出。

    打包后的窗口化程序如果抛未捕获异常，PyInstaller 会弹一个模态框
    （"Unhandled exception in script"），该框会阻塞退出流程。因此这里
    主动写日志、写 crash.log，并尽量用系统对话框提示，而不是把异常丢给
    PyInstaller 的兜底处理。
    """
    import desktop_logging

    logger = desktop_logging.configure_logging()
    logger.error("启动失败：%s\n%s", title, detail)

    try:
        desktop_logging._write_crash(f"=== 启动失败: {title} ===\n{detail}\n")
    except Exception:  # noqa: BLE001 - 崩溃日志写入失败不应掩盖原始问题
        logger.debug("写入 crash.log 失败", exc_info=True)

    message = (
        f"{detail}\n\n"
        f"日志目录：{desktop_logging.log_path_for_display()}"
    )
    print(f"ERROR: {title}\n{message}")

    # 有控制台时用 print 即可；无控制台时尝试系统消息框，最差也要醒目
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, f"AI Serial Bridge - {title}", 0x10)
    except Exception:  # noqa: BLE001 - 非 Windows 或无法弹窗时静默跳过
        pass


def _run_desktop(base_dir: Path, dist_dir: Path, local_runtime, instance_id):
    port = _find_free_port(8000)
    host = '127.0.0.1'

    # 打包/桌面模式下前端产物的缺失必须在导入 main 之前拦下。
    # 否则 main 在导入期抛出 RuntimeError，PyInstaller 的窗口化模式会弹
    # "Unhandled exception in script" 模态框，把进程挂住不退出。
    backend_dir = base_dir / 'backend'
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    import frontend_assets

    resolved_dist = _resolve_bundle_dir(base_dir)

    # 无构建产物时必须回退到 Vite 开发服务器，而它的代理固定指向 8000
    if resolved_dist is None and port != 8000:
        print("ERROR: 开发模式要求端口 8000 可用，因为 Vite 代理固定连接该端口")
        sys.exit(1)

    # 设置环境变量，让后端适配
    auth_token = local_runtime.load_or_create_token(
        os.environ.get('AI_SERIAL_TOKEN', '')
    )
    os.environ['AI_SERIAL_TOKEN'] = auth_token
    os.environ['AI_SERIAL_INSTANCE_ID'] = instance_id
    os.environ['AI_SERIAL_PORT'] = str(port)
    os.environ['AI_SERIAL_HOST'] = host
    os.environ['AI_SERIAL_DESKTOP'] = '1'  # 标记：桌面模式

    if resolved_dist is None:
        _report_startup_failure(
            frontend_assets.describe_missing_dist(base_dir=base_dir),
            '未找到前端构建产物',
        )
        sys.exit(1)

    # --- 在后台线程启动 FastAPI ---
    import uvicorn
    try:
        from main import app  # 路径与环境变量设置后再导入
    except Exception as exc:  # noqa: BLE001 - 启动期错误需要可读提示
        import traceback

        _report_startup_failure(
            f"后端模块导入失败：{exc}\n\n{traceback.format_exc()}",
            '后端启动失败',
        )
        sys.exit(1)

    # pythonw.exe（无控制台）下 sys.stdout / sys.stderr 为 None，
    # uvicorn 的日志 formatter 会调用 sys.stdout.isatty() 而抛 AttributeError。
    # 用无缓冲的空写入器兜底，保证日志初始化总是安全。
    _ensure_std_streams()

    server = uvicorn.Server(uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level='warning',
    ))

    def run_server():
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    try:
        server_thread.start()

        # --- 等待服务器就绪 ---
        print(f"[AI Serial Bridge] 正在启动服务 {host}:{port}...")
        if not _wait_for_server(host, port, instance_id):
            print(f"ERROR: 后端服务启动失败 {host}:{port}")
            sys.exit(1)
        print("[AI Serial Bridge] 服务已就绪")
        local_runtime.write_runtime_manifest(
            f'http://{host}:{port}',
            pid=os.getpid(),
            instance_id=instance_id,
        )

        # --- 打开 PyWebView 窗口 ---
        import webview

        if resolved_dist is not None:
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
    finally:
        server.should_exit = True
        local_runtime.remove_runtime_manifest(instance_id)
        if server_thread.is_alive():
            server_thread.join(timeout=5)


def main():
    # 必须在导入后端模块之前完成解释器校正
    _ensure_venv_interpreter()

    # 无控制台运行时 stdout/stderr 为 None，先兜底再安装日志
    _ensure_std_streams()

    base_dir = Path(_get_base_dir())
    dist_dir = base_dir / 'frontend' / 'dist'

    # 把 backend 加入 sys.path，才能导入 desktop_logging
    backend_dir = base_dir / 'backend'
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    # 崩溃与运行日志落盘：console=False / pythonw 下这是唯一的排障入口
    import desktop_logging

    logger = desktop_logging.configure_logging()
    desktop_logging.install_exception_hooks()
    logger.info("桌面程序启动: base_dir=%s frozen=%s", base_dir, getattr(sys, 'frozen', False))

    if not getattr(sys, 'frozen', False) and _frontend_build_is_stale(base_dir):
        message = (
            "frontend/dist 比前端源码旧，拒绝加载过期资源。\n"
            "请执行：cd frontend && npm run build"
        )
        print(f"ERROR: {message}")
        logger.error(message)
        sys.exit(1)

    import local_runtime

    try:
        with local_runtime.desktop_instance_lock() as instance_id:
            _run_desktop(base_dir, dist_dir, local_runtime, instance_id)
    except local_runtime.DesktopAlreadyRunning:
        message = "AI Serial Bridge 桌面程序已在运行"
        print(f"ERROR: {message}")
        logger.warning(message)
        sys.exit(1)
    except SystemExit:
        raise
    except BaseException:
        # 启动阶段失败（例如前端产物缺失的 fail-fast）也要落盘
        logger.exception("桌面程序异常退出；详细日志: %s", desktop_logging.log_path_for_display())
        raise
    finally:
        logger.info("桌面程序退出")


if __name__ == '__main__':
    main()
