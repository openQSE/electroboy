from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from electroboy.service import create_server


CHROME = shutil.which("google-chrome") or shutil.which("chromium")


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_shell_loads_and_connects(tmp_path: Path) -> None:
    server = create_server(tmp_path / "service", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    profile = tmp_path / "chrome-profile"
    try:
        completed = subprocess.run(
            [
                str(CHROME),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=4000",
                "--dump-dom",
                f"http://127.0.0.1:{port}/",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert completed.returncode == 0, completed.stdout
    assert 'id="connection" class="connection">connected' in completed.stdout
    assert 'data-stage="requirements"' in completed.stdout
    assert 'id="sessionSwitcher"' in completed.stdout
