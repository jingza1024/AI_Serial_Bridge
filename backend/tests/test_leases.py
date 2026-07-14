"""端口租约测试：单写者、多观察者、过期与释放。"""

from leases import PortLeaseManager


def test_single_writer_and_observer_conflict():
    now = [100.0]
    leases = PortLeaseManager(clock=lambda: now[0])

    first = leases.acquire("COM1", "web-a", "Web UI", ttl=30)
    assert first.acquired is True
    assert first.lease.owner_id == "web-a"

    second = leases.acquire("COM1", "mcp-b", "MCP", ttl=30)
    assert second.acquired is False
    assert second.lease.owner_id == "web-a"


def test_owner_renews_and_expired_lease_can_be_acquired():
    now = [100.0]
    leases = PortLeaseManager(clock=lambda: now[0])
    leases.acquire("COM1", "web-a", "Web UI", ttl=10)

    now[0] = 105.0
    renewed = leases.ensure_writer("COM1", "web-a", "Web UI", ttl=20)
    assert renewed.acquired is True
    assert renewed.lease.expires_at == 125.0

    now[0] = 126.0
    acquired = leases.acquire("COM1", "mcp-b", "MCP", ttl=10)
    assert acquired.acquired is True
    assert acquired.lease.owner_id == "mcp-b"


def test_release_owner_clears_all_owned_ports():
    leases = PortLeaseManager()
    leases.acquire("COM1", "web-a", "Web UI")
    leases.acquire("COM2", "web-a", "Web UI")
    leases.acquire("COM3", "mcp-b", "MCP")

    assert set(leases.release_owner("web-a")) == {"COM1", "COM2"}
    assert leases.get("COM1") is None
    assert leases.get("COM3").owner_id == "mcp-b"
