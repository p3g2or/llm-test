"""Exercise an extracted release over HTTP with in-memory storage."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile


def main() -> None:
    archive = Path(sys.argv[1]).resolve()
    with TemporaryDirectory(prefix="fieldnotes-smoke-") as directory:
        with ZipFile(archive) as package:
            package.extractall(directory)
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        env = {
            **os.environ,
            "STORAGE_BACKEND": "memory",
            "BOARD_TITLE": "Release Smoke",
            "PYTHONPATH": directory,
            "STATIC_DIR": f"{directory}/fieldnotes/static",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "fieldnotes.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=directory,
            env=env,
        )
        base = f"http://127.0.0.1:{port}"

        def request(path: str, method: str = "GET", data: object = None) -> tuple[int, bytes]:
            body = None if data is None else json.dumps(data).encode()
            req = Request(
                base + path, data=body, method=method, headers={"Content-Type": "application/json"}
            )
            with urlopen(req, timeout=3) as response:
                return response.status, response.read()

        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Release server exited before becoming healthy")
                try:
                    assert request("/api/health")[0] == 200
                    break
                except URLError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Release server did not become healthy")
            assert b'<main id="app">' in request("/")[1]
            for asset in (Path(directory) / "fieldnotes/static/assets").iterdir():
                assert request(f"/assets/{asset.name}")[0] == 200
            config = json.loads(request("/api/config")[1])
            assert config["board_title"] == "Release Smoke"
            status, payload = request(
                "/api/notes",
                "POST",
                {
                    "title": "Release smoke",
                    "body": "Packaged app works",
                    "category": "work",
                },
            )
            assert status == 201
            note = json.loads(payload)
            assert json.loads(request(f"/api/notes/{note['id']}")[1]) == note
            assert json.loads(request("/api/notes?category=work&q=packaged")[1]) == [note]
            assert json.loads(request("/api/summary")[1])["total"] == 1
            assert request(f"/api/notes/{note['id']}", "DELETE")[0] == 204
            assert json.loads(request("/api/notes")[1]) == []
            print("Release smoke passed: frontend assets, config, note lifecycle, filters, summary")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
