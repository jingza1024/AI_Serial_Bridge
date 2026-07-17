"""Run one authenticated, read-only automation probe against a real serial device."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify one non-destructive Linux serial automation probe.")
    parser.add_argument("--port", default=os.environ.get("AI_SERIAL_TEST_PORT", "COM17"))
    parser.add_argument("--baudrate", type=int, default=int(os.environ.get("AI_SERIAL_TEST_BAUDRATE", "115200")))
    parser.add_argument("--api-port", type=int, default=8017)
    return parser.parse_args()


def request_json(base: str, path: str, token: str, client_id: str, *, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-AI-Serial-Client": client_id,
            "X-AI-Serial-Client-Label": "Hardware verification",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def wait_for_backend(base: str, token: str, client_id: str) -> None:
    deadline = time.monotonic() + 15
    last_error = "backend did not start"
    while time.monotonic() < deadline:
        try:
            status, payload = request_json(base, "/api/health", token, client_id)
            if status == 200 and payload.get("status") == "ok":
                return
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(last_error)


async def run_mcp_probe(environment: dict[str, str], port: str, baudrate: int, base: str) -> dict[str, str]:
    mcp_environment = {
        **environment,
        "AI_SERIAL_API_URL": base,
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(BACKEND / "mcp_server.py")],
        env=mcp_environment,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            async def call(name: str, arguments: dict) -> str:
                result = await session.call_tool(name, arguments)
                text = "\n".join(getattr(item, "text", "") for item in result.content)
                if result.isError:
                    raise RuntimeError(f"MCP {name} failed: {text}")
                return text

            opened = False
            try:
                open_text = await call("serial_open", {"port": port, "baudrate": baudrate})
                if "已打开" not in open_text and "opened" not in open_text.lower():
                    raise RuntimeError(f"MCP serial_open did not succeed: {open_text}")
                opened = True
                lease_text = await call("serial_get_lease", {"port": port})
                if "MCP" not in lease_text:
                    raise RuntimeError(f"MCP lease owner was not reported: {lease_text}")
                macro_text = await call(
                    "serial_run_macro",
                    {"port": port, "macro_id": "linux-uname", "run_id": "hardware-check-mcp"},
                )
                if "completed" not in macro_text or "Linux" not in macro_text:
                    raise RuntimeError(f"MCP diagnostic macro did not return Linux output: {macro_text[:300]}")

                health_text = ""
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    health_text = await call("serial_get_health", {"port": port, "limit": 20})
                    if "Linux response observed" in health_text:
                        break
                    await asyncio.sleep(0.25)
                if "Linux response observed" not in health_text:
                    raise RuntimeError(f"MCP health observation missing: {health_text}")
                close_text = await call("serial_close", {"port": port})
                opened = False
                if "已关闭" not in close_text and "closed" not in close_text.lower():
                    raise RuntimeError(f"MCP serial_close did not succeed: {close_text}")
                return {"lease": lease_text, "macro": macro_text, "health": health_text, "close": close_text}
            finally:
                if opened:
                    await call("serial_close", {"port": port})


def main() -> int:
    args = parse_args()
    token = secrets.token_urlsafe(32)
    client_id = f"hardware-check-{secrets.token_hex(6)}"
    base = f"http://127.0.0.1:{args.api_port}"
    with tempfile.TemporaryDirectory(prefix="ai-serial-hardware-") as temp_dir:
        environment = os.environ.copy()
        environment.update({
            "AI_SERIAL_TOKEN": token,
            "AI_SERIAL_LOG_DIR": str(Path(temp_dir) / "logs"),
            "AI_SERIAL_AUTOMATION_FILE": str(Path(temp_dir) / "automations.json"),
        })
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.api_port)],
            cwd=BACKEND,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_backend(base, token, client_id)
            _, ports = request_json(base, "/api/ports", token, client_id)
            available = {item.get("device") for item in ports}
            if args.port not in available:
                raise RuntimeError(f"{args.port} is not available; detected ports: {sorted(p for p in available if p)}")

            request_json(
                base,
                "/api/automations/rules/linux-response",
                token,
                client_id,
                method="PUT",
                payload={
                    "id": "linux-response",
                    "name": "Linux response",
                    "pattern": "Linux",
                    "severity": "info",
                    "message": "Linux response observed",
                    "cooldown_seconds": 0,
                    "enabled": True,
                },
            )
            request_json(
                base,
                "/api/automations/macros/linux-uname",
                token,
                client_id,
                method="PUT",
                payload={
                    "id": "linux-uname",
                    "name": "Linux uname",
                    "steps": [{"command": "uname -a", "newline": "\r", "wait_seconds": 1}],
                    "enabled": True,
                },
            )
            probe = asyncio.run(asyncio.wait_for(
                run_mcp_probe(environment, args.port, args.baudrate, base),
                timeout=30,
            ))
            _, status_payload = request_json(base, f"/api/status?port={args.port}", token, client_id)
            if status_payload.get("is_open"):
                raise RuntimeError(f"{args.port} remained open after close")

            print(json.dumps({
                "port": args.port,
                "baudrate": args.baudrate,
                "mcp_lease_verified": True,
                "mcp_macro_completed": "completed" in probe["macro"],
                "health_observed": True,
                "port_released": True,
            }, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Hardware verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
