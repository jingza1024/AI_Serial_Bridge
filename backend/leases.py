"""Thread-safe single-writer leases for shared serial ports."""

from dataclasses import dataclass
import threading
import time
from typing import Callable


@dataclass(frozen=True)
class PortLease:
    owner_id: str
    owner_label: str
    expires_at: float


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    lease: PortLease


class PortLeaseManager:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._leases: dict[str, PortLease] = {}

    def _active_locked(self, port: str) -> PortLease | None:
        lease = self._leases.get(port)
        if lease is not None and lease.expires_at <= self._clock():
            self._leases.pop(port, None)
            return None
        return lease

    def get(self, port: str) -> PortLease | None:
        with self._lock:
            return self._active_locked(port)

    def acquire(
        self,
        port: str,
        owner_id: str,
        owner_label: str,
        ttl: float = 30.0,
    ) -> LeaseResult:
        ttl = min(max(float(ttl), 5.0), 300.0)
        with self._lock:
            current = self._active_locked(port)
            if current is not None and current.owner_id != owner_id:
                return LeaseResult(False, current)
            lease = PortLease(owner_id, owner_label, self._clock() + ttl)
            self._leases[port] = lease
            return LeaseResult(True, lease)

    def ensure_writer(
        self,
        port: str,
        owner_id: str,
        owner_label: str,
        ttl: float = 30.0,
    ) -> LeaseResult:
        return self.acquire(port, owner_id, owner_label, ttl)

    def release(self, port: str, owner_id: str) -> bool:
        with self._lock:
            current = self._active_locked(port)
            if current is None or current.owner_id != owner_id:
                return False
            self._leases.pop(port, None)
            return True

    def release_owner(self, owner_id: str) -> list[str]:
        with self._lock:
            released = [
                port for port, lease in self._leases.items()
                if lease.owner_id == owner_id
            ]
            for port in released:
                self._leases.pop(port, None)
            return released

    def clear(self, port: str) -> None:
        with self._lock:
            self._leases.pop(port, None)

    def clear_all(self) -> None:
        with self._lock:
            self._leases.clear()


port_leases = PortLeaseManager()
