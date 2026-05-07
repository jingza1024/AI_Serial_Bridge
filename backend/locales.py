"""Backend i18n support"""

import contextvars

_lang_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("_lang", default="zh")

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
    if lang in MESSAGES:
        _lang_ctx.set(lang)


def get_lang() -> str:
    return _lang_ctx.get()


def t(key: str, **kwargs) -> str:
    lang = _lang_ctx.get()
    template = MESSAGES.get(lang, MESSAGES["zh"]).get(key, key)
    return template.format(**kwargs)
