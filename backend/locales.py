"""Backend i18n support.

语言状态使用模块级变量 + 线程锁保存，确保：
1. set_lang() 设置后对所有请求、所有后台线程（串口读线程）均生效；
2. t() 在任意线程读取到一致的语言。
（早期版本误用 contextvars.ContextVar，其上下文不会跨请求/跨线程传播，导致后端语言切换无效。）
"""

import threading

_lang_lock = threading.Lock()
_lang = "zh"  # 全局后端语言，受 _lang_lock 保护

MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "port_already_open_close_first": "串口已打开，先关闭当前连接: {port}",
        "port_opened": "串口已打开: {port} @ {baudrate}bps",
        "port_open_failed": "打开串口失败: {error}",
        "port_closed": "串口已关闭: {port}",
        "port_close_failed": "关闭串口失败: {error}",
        "port_not_open": "错误: 串口未打开",
        "send_failed": "发送失败: {error}",
        "read_error": "读取错误: {error}",
    },
    "en": {
        "port_already_open_close_first": "Port already open, closing current: {port}",
        "port_opened": "Port opened: {port} @ {baudrate}bps",
        "port_open_failed": "Failed to open port: {error}",
        "port_closed": "Port closed: {port}",
        "port_close_failed": "Failed to close port: {error}",
        "port_not_open": "Error: Port not open",
        "send_failed": "Send failed: {error}",
        "read_error": "Read error: {error}",
    },
}


def set_lang(lang: str) -> None:
    """设置全局后端语言（线程安全，对所有请求/线程生效）。"""
    global _lang
    if lang in MESSAGES:
        with _lang_lock:
            _lang = lang


def get_lang() -> str:
    with _lang_lock:
        return _lang


def t(key: str, **kwargs) -> str:
    """按当前后端语言渲染消息模板，未找到时返回 key 本身。"""
    with _lang_lock:
        lang = _lang
    template = MESSAGES.get(lang, MESSAGES["zh"]).get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
