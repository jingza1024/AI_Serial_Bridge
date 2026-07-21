"""User-scoped pairing state shared by the desktop and MCP processes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import threading
import time
from collections.abc import Mapping
from urllib.parse import urlparse

if os.name == "nt":
    import msvcrt
else:
    import fcntl


STATE_VERSION = 1
SERVICE_NAME = "ai-serial-bridge"
DEFAULT_API_URL = "http://127.0.0.1:8000"
STATE_DIR_ENV = "AI_SERIAL_STATE_DIR"


class RuntimeConfigError(RuntimeError):
    """Raised when local pairing state is malformed or unsafe."""


class DesktopAlreadyRunning(RuntimeConfigError):
    """Raised when another desktop process holds the user-scoped lock."""


@dataclass(frozen=True)
class RuntimeManifest:
    version: int
    service: str
    api_url: str
    pid: int
    instance_id: str
    started_at: float


@dataclass(frozen=True)
class ConnectionTarget:
    api_url: str
    token: str
    source: str
    instance_id: str = ""


def get_state_dir(
    state_dir: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if state_dir is not None:
        return Path(state_dir).expanduser()
    values = os.environ if env is None else env
    override = values.get(STATE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ai-serial-bridge"


def credential_path(state_dir: str | os.PathLike[str] | None = None) -> Path:
    return get_state_dir(state_dir) / "credentials.json"


def runtime_manifest_path(state_dir: str | os.PathLike[str] | None = None) -> Path:
    return get_state_dir(state_dir) / "runtime.json"


def _ensure_state_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _atomic_write_json(path: Path, payload: dict) -> None:
    _ensure_state_dir(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeConfigError(f"invalid {label}: {path}")
    return payload


def load_token(state_dir: str | os.PathLike[str] | None = None) -> str:
    path = credential_path(state_dir)
    try:
        payload = _read_json(path, "credential file")
    except FileNotFoundError:
        return ""
    token = payload.get("token")
    if payload.get("version") != STATE_VERSION or not isinstance(token, str) or not token.strip():
        raise RuntimeConfigError(f"invalid credential file: {path}")
    return token.strip()


def _acquire_lock(
    lock_path: Path,
    timeout: float = 3.0,
    *,
    offset: int = 0,
) -> int:
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    size = os.fstat(descriptor).st_size
    if size <= offset:
        os.lseek(descriptor, 0, os.SEEK_END)
        os.write(descriptor, b"0" * (offset + 1 - size))
        os.fsync(descriptor)
    try:
        lock_path.chmod(0o600)
    except OSError:
        pass

    deadline = time.monotonic() + timeout
    while True:
        try:
            os.lseek(descriptor, offset, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.lockf(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                    1,
                    offset,
                    os.SEEK_SET,
                )
            return descriptor
        except OSError:
            if time.monotonic() >= deadline:
                os.close(descriptor)
                raise RuntimeConfigError(f"timed out waiting for local state lock: {lock_path}")
            time.sleep(0.02)


def _release_lock(descriptor: int, *, offset: int = 0) -> None:
    try:
        os.lseek(descriptor, offset, os.SEEK_SET)
        if os.name == "nt":
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.lockf(
                descriptor,
                fcntl.LOCK_UN,
                1,
                offset,
                os.SEEK_SET,
            )
    finally:
        os.close(descriptor)


# fcntl/msvcrt byte locks are process-scoped, so concurrent threads in the
# same process must also take a threading.Lock or they will both succeed.
_STATE_THREAD_LOCKS: dict[str, threading.Lock] = {}
_STATE_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    key = str(lock_path.resolve(strict=False))
    with _STATE_THREAD_LOCKS_GUARD:
        lock = _STATE_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _STATE_THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _state_lock(lock_path: Path, timeout: float = 3.0):
    _ensure_state_dir(lock_path.parent)
    thread_lock = _thread_lock_for(lock_path)
    deadline = time.monotonic() + timeout
    while True:
        acquired = thread_lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise RuntimeConfigError(f"timed out waiting for local state lock: {lock_path}")
    try:
        remaining = max(0.0, deadline - time.monotonic())
        descriptor = _acquire_lock(lock_path, timeout=remaining)
        try:
            yield
        finally:
            _release_lock(descriptor)
    finally:
        thread_lock.release()


_DESKTOP_PROCESS_LOCK = threading.Lock()
_DESKTOP_INSTANCE_ID = ""
_DESKTOP_ID_OFFSET = 64
_DESKTOP_ID_SIZE = 128


def _set_lock_identity(descriptor: int, instance_id: str) -> None:
    encoded = instance_id.encode("ascii")
    if len(encoded) >= _DESKTOP_ID_SIZE:
        raise RuntimeConfigError("desktop instance id is too long")
    os.lseek(descriptor, _DESKTOP_ID_OFFSET, os.SEEK_SET)
    os.write(descriptor, encoded.ljust(_DESKTOP_ID_SIZE, b"\0"))
    os.fsync(descriptor)


def _read_lock_identity(lock_path: Path) -> str:
    descriptor = os.open(lock_path, os.O_RDONLY)
    try:
        os.lseek(descriptor, _DESKTOP_ID_OFFSET, os.SEEK_SET)
        payload = os.read(descriptor, _DESKTOP_ID_SIZE)
    finally:
        os.close(descriptor)
    return payload.split(b"\0", 1)[0].decode("ascii").strip()


@contextmanager
def desktop_instance_lock(
    state_dir: str | os.PathLike[str] | None = None,
    *,
    timeout: float = 0.1,
):
    global _DESKTOP_INSTANCE_ID
    acquired = _DESKTOP_PROCESS_LOCK.acquire(timeout=max(0.0, timeout))
    if not acquired:
        raise DesktopAlreadyRunning("another desktop instance is already running")
    try:
        lock_path = get_state_dir(state_dir) / ".desktop.lock"
        _ensure_state_dir(lock_path.parent)
        try:
            gate_descriptor = _acquire_lock(lock_path, timeout=timeout)
        except RuntimeConfigError as exc:
            raise DesktopAlreadyRunning(
                "another desktop instance is already running"
            ) from exc
        try:
            instance_id = secrets.token_urlsafe(18)
            _set_lock_identity(gate_descriptor, instance_id)
            active_descriptor = _acquire_lock(
                lock_path,
                timeout=timeout,
                offset=1,
            )
            _DESKTOP_INSTANCE_ID = instance_id
            try:
                yield instance_id
            finally:
                _DESKTOP_INSTANCE_ID = ""
                _release_lock(active_descriptor, offset=1)
        finally:
            _release_lock(gate_descriptor)
    finally:
        _DESKTOP_PROCESS_LOCK.release()


def _desktop_instance_is_active(
    instance_id: str,
    state_dir: str | os.PathLike[str] | None = None,
) -> bool:
    if _DESKTOP_PROCESS_LOCK.locked():
        return _DESKTOP_INSTANCE_ID == instance_id
    lock_path = get_state_dir(state_dir) / ".desktop.lock"
    _ensure_state_dir(lock_path.parent)
    try:
        descriptor = _acquire_lock(lock_path, timeout=0.0, offset=1)
    except RuntimeConfigError:
        try:
            return _read_lock_identity(lock_path) == instance_id
        except (OSError, UnicodeDecodeError):
            return False
    _release_lock(descriptor, offset=1)
    return False


def load_or_create_token(
    explicit_token: str | None = None,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    token_factory=None,
) -> str:
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    existing = load_token(state_dir)
    if existing:
        return existing

    directory = get_state_dir(state_dir)
    lock_path = directory / ".credentials.lock"
    with _state_lock(lock_path):
        existing = load_token(state_dir)
        if existing:
            return existing
        factory = token_factory or (lambda: secrets.token_urlsafe(32))
        token = str(factory()).strip()
        if not token:
            raise RuntimeConfigError("credential generator returned an empty token")
        _atomic_write_json(
            credential_path(state_dir),
            {"version": STATE_VERSION, "token": token},
        )
        return token


def _normalize_url(
    url: str,
    *,
    require_loopback: bool,
    allow_path: bool = False,
) -> str:
    value = url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeConfigError(f"invalid API URL: {url}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeConfigError(f"invalid API URL: {url}")
    if not allow_path and parsed.path not in {"", "/"}:
        raise RuntimeConfigError(f"API URL must not include a path: {url}")
    if require_loopback and parsed.hostname.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeConfigError("runtime manifest API URL must use a loopback host")
    return value


def is_loopback_url(url: str) -> bool:
    try:
        parsed = urlparse(
            _normalize_url(url, require_loopback=False, allow_path=True)
        )
    except RuntimeConfigError:
        return False
    return parsed.hostname.lower() in {"127.0.0.1", "localhost", "::1"}


def write_runtime_manifest(
    api_url: str,
    *,
    pid: int,
    instance_id: str,
    state_dir: str | os.PathLike[str] | None = None,
    started_at: float | None = None,
) -> RuntimeManifest:
    normalized_url = _normalize_url(api_url, require_loopback=True)
    if int(pid) <= 0 or not instance_id.strip():
        raise RuntimeConfigError("runtime manifest requires a valid pid and instance id")
    manifest = RuntimeManifest(
        version=STATE_VERSION,
        service=SERVICE_NAME,
        api_url=normalized_url,
        pid=int(pid),
        instance_id=instance_id.strip(),
        started_at=float(time.time() if started_at is None else started_at),
    )
    lock_path = get_state_dir(state_dir) / ".runtime.lock"
    with _state_lock(lock_path):
        _atomic_write_json(runtime_manifest_path(state_dir), manifest.__dict__)
    return manifest


def read_runtime_manifest(
    state_dir: str | os.PathLike[str] | None = None,
) -> RuntimeManifest | None:
    path = runtime_manifest_path(state_dir)
    try:
        payload = _read_json(path, "runtime manifest")
    except FileNotFoundError:
        return None
    try:
        manifest = RuntimeManifest(
            version=int(payload["version"]),
            service=str(payload["service"]),
            api_url=_normalize_url(str(payload["api_url"]), require_loopback=True),
            pid=int(payload["pid"]),
            instance_id=str(payload["instance_id"]).strip(),
            started_at=float(payload["started_at"]),
        )
    except (KeyError, TypeError, ValueError, RuntimeConfigError) as exc:
        raise RuntimeConfigError(f"invalid runtime manifest: {path}") from exc
    if (
        manifest.version != STATE_VERSION
        or manifest.service != SERVICE_NAME
        or manifest.pid <= 0
        or not manifest.instance_id
    ):
        raise RuntimeConfigError(f"invalid runtime manifest: {path}")
    return manifest


def remove_runtime_manifest(
    instance_id: str,
    *,
    state_dir: str | os.PathLike[str] | None = None,
) -> bool:
    lock_path = get_state_dir(state_dir) / ".runtime.lock"
    with _state_lock(lock_path):
        try:
            manifest = read_runtime_manifest(state_dir)
        except RuntimeConfigError:
            return False
        if manifest is None or manifest.instance_id != instance_id:
            return False
        try:
            runtime_manifest_path(state_dir).unlink()
        except FileNotFoundError:
            return False
        return True


def resolve_connection_targets(
    *,
    env: Mapping[str, str] | None = None,
    state_dir: str | os.PathLike[str] | None = None,
) -> list[ConnectionTarget]:
    values = os.environ if env is None else env
    env_url = values.get("AI_SERIAL_API_URL", "").strip()
    env_token = values.get("AI_SERIAL_TOKEN", "").strip()
    targets: list[ConnectionTarget] = []

    def add(api_url: str, token: str, source: str, instance_id: str = "") -> None:
        candidate = ConnectionTarget(api_url, token, source, instance_id)
        if candidate not in targets:
            targets.append(candidate)

    explicit_url = ""
    if env_url:
        explicit_url = _normalize_url(
            env_url,
            require_loopback=False,
            allow_path=True,
        )
        if not is_loopback_url(explicit_url):
            return [ConnectionTarget(explicit_url, env_token, "environment")]

    def optional_manifest() -> RuntimeManifest | None:
        try:
            manifest = read_runtime_manifest(state_dir)
        except RuntimeConfigError:
            return None
        if manifest is not None and not _desktop_instance_is_active(
            manifest.instance_id,
            state_dir,
        ):
            remove_runtime_manifest(manifest.instance_id, state_dir=state_dir)
            return None
        return manifest

    def optional_saved_token(manifest: RuntimeManifest | None) -> str:
        if manifest is None:
            return ""
        try:
            return load_token(state_dir)
        except RuntimeConfigError:
            return ""

    if env_url:
        add(explicit_url, env_token, "environment")
        manifest = optional_manifest()
        if manifest is not None:
            saved_token = optional_saved_token(manifest)
            if env_token:
                add(
                    manifest.api_url,
                    env_token,
                    "desktop-runtime",
                    manifest.instance_id,
                )
            else:
                add(
                    manifest.api_url,
                    saved_token,
                    "desktop-runtime",
                    manifest.instance_id,
                )
            if env_token and saved_token and saved_token != env_token:
                add(
                    manifest.api_url,
                    saved_token,
                    "local-credential",
                    manifest.instance_id,
                )
        return targets

    if env_token:
        manifest = optional_manifest()
        if manifest is not None:
            add(
                manifest.api_url,
                env_token,
                "desktop-runtime",
                manifest.instance_id,
            )
            saved_token = optional_saved_token(manifest)
            if saved_token and saved_token != env_token:
                add(
                    manifest.api_url,
                    saved_token,
                    "local-credential",
                    manifest.instance_id,
                )
        add(DEFAULT_API_URL, env_token, "default")
        return targets

    manifest = optional_manifest()
    if manifest is not None:
        saved_token = optional_saved_token(manifest)
        add(
            manifest.api_url,
            saved_token,
            "desktop-runtime",
            manifest.instance_id,
        )

    add(DEFAULT_API_URL, "", "default")
    return targets
