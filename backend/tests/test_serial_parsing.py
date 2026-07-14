"""串口行解析测试：_split_lines / _drain_lines 的各类换行与编码边界。"""
from serial_manager import SerialManager


def _drain_capture(mgr, buffer: bytes):
    """用捕获式 _notify 跑一次 drain，返回 [content, ...]。"""
    captured = []
    mgr._notify = lambda msg: captured.append(msg.content)
    b = bytearray(buffer)
    mgr._drain_lines(b)
    return captured, b


def _drain_messages(mgr, buffer: bytes):
    captured = []
    mgr._notify = captured.append
    b = bytearray(buffer)
    mgr._drain_lines(b)
    return captured, b


def test_split_crlf():
    m = SerialManager()
    b = bytearray(b"a\r\nb\r\n")
    assert m._split_lines(b) == [b"a", b"b"]
    assert b == b""


def test_split_lf_only():
    m = SerialManager()
    b = bytearray(b"a\nb\n")
    assert m._split_lines(b) == [b"a", b"b"]
    assert b == b""


def test_split_cr_only():
    m = SerialManager()
    b = bytearray(b"a\rb\r")
    assert m._split_lines(b) == [b"a", b"b"]
    assert b == b""


def test_split_mixed_with_empty_line():
    # a\n b\r \r\n c\n  -> a, b, (空行), c
    m = SerialManager()
    b = bytearray(b"a\nb\r\r\nc\n")
    assert m._split_lines(b) == [b"a", b"b", b"", b"c"]
    assert b == b""


def test_split_partial_not_consumed():
    m = SerialManager()
    b = bytearray(b"partial_without_newline")
    assert m._split_lines(b) == []
    assert b == b"partial_without_newline"


def test_split_utf8_multibyte():
    # "你" = E4 BD A0
    m = SerialManager()
    b = bytearray(b"\xe4\xbd\xa0\r\n")
    assert m._split_lines(b) == [b"\xe4\xbd\xa0"]
    assert b == b""


def test_drain_decodes_utf8():
    m = SerialManager()
    captured, _ = _drain_capture(m, b"\xe4\xbd\xa0\r\n")
    assert captured == ["你\r\n"]


def test_line_message_raw_bytes_preserve_crlf():
    m = SerialManager()
    captured, remaining = _drain_messages(m, b"abc\r\n")
    assert remaining == bytearray()
    assert captured[0].raw_bytes == b"abc\r\n"


def test_line_message_raw_bytes_preserve_mixed_delimiters():
    m = SerialManager()
    captured, _ = _drain_messages(m, b"a\nb\rc\r\n")
    assert [message.raw_bytes for message in captured] == [b"a\n", b"b\r", b"c\r\n"]


def test_drain_hex_fallback_on_invalid_utf8():
    m = SerialManager()
    captured, _ = _drain_capture(m, b"\xff\xfe\r\n")
    # 0xff 0xfe 不是合法 UTF-8，应回退为 hex
    assert captured == ["fffe\r\n"]


def test_drain_empty_line_emits_crlf():
    m = SerialManager()
    captured, _ = _drain_capture(m, b"\r\n")
    assert captured == ["\r\n"]


def test_drain_leaves_partial_in_buffer():
    m = SerialManager()
    captured, remaining = _drain_capture(m, b"line\r\npartial")
    assert captured == ["line\r\n"]
    assert remaining == bytearray(b"partial")
