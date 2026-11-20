"""Shared fixtures."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

SERVER = Path(__file__).with_name("modbus_server.py")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Load custom_components/ and allow the local test server's sockets."""
    return


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def start_meter():
    """Start simulated meters; returns a function (framer, mode) -> port."""
    procs = []

    def _start(framer: str = "socket", mode: str = "full") -> int:
        port = _free_port()
        procs.append(
            subprocess.Popen(
                [sys.executable, str(SERVER), str(port), framer, mode],
                stderr=subprocess.DEVNULL,
            )
        )
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                return port
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("simulated meter did not start")

    yield _start
    for proc in procs:
        proc.kill()
        proc.wait()


@pytest.fixture
def meter(start_meter) -> int:
    """A simulated meter speaking Modbus TCP; returns its port."""
    return start_meter()


@pytest.fixture
def free_port() -> int:
    """A port nothing listens on."""
    return _free_port()
