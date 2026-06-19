"""Layer 3: Rendering Engine — msedge.exe headless wrapper.

Locates msedge.exe on the system, invokes it with ``--print-to-pdf``
on the normalized HTML, and reports any failure with a structured error.
"""
from __future__ import annotations

import os
import base64
import json
import socket
import shlex
import shutil
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

import websocket


# ---------- Errors ----------

class RendererError(Exception):
    """Base for renderer failures."""


class EdgeNotFoundError(RendererError):
    """msedge.exe could not be located."""


# ---------- Locate msedge ----------

_DEFAULT_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # Per-user install
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def find_msedge() -> Optional[str]:
    """Return absolute path to msedge.exe, or None if not found."""
    # 1. PATH
    on_path = shutil.which("msedge") or shutil.which("msedge.exe")
    if on_path:
        return on_path
    # 2. Hardcoded candidates
    for p in _DEFAULT_EDGE_PATHS:
        if os.path.isfile(p):
            return p
    # 3. Walk the Edge application directory for the newest version
    base = r"C:\Program Files (x86)\Microsoft\Edge\Application"
    if os.path.isdir(base):
        candidates = []
        for entry in os.listdir(base):
            full = os.path.join(base, entry, "msedge.exe")
            if os.path.isfile(full):
                candidates.append(full)
        if candidates:
            # Prefer the newest version directory (highest semantic version)
            candidates.sort(key=_ver_key, reverse=True)
            return candidates[0]
    return None


def _ver_key(path: str) -> tuple[int, ...]:
    parent = os.path.basename(os.path.dirname(path))
    parts = parent.split(".")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _read_devtools_json(port: int, endpoint: str) -> dict | list:
    url = f"http://127.0.0.1:{port}{endpoint}"
    with urllib.request.urlopen(url, timeout=1) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_for_devtools_page_ws(port: int, timeout: float) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            _read_devtools_json(port, "/json/version")
            targets = _read_devtools_json(port, "/json/list")
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        except Exception as e:
            last_error = e
            time.sleep(0.1)
    raise RendererError(f"msedge DevTools page endpoint did not start: {last_error}")


def _build_cdp_edge_cmd(edge: str, user_data_dir: Path, port: int) -> list[str]:
    return [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
        "--disable-extensions",
        "--disable-features=Translate",
        "about:blank",
    ]


def _cdp_print_to_pdf(
    edge: str,
    html_path: str,
    pdf_path: str,
    user_data_dir: Path,
    *,
    timeout: int,
) -> None:
    """Fallback renderer using Chrome DevTools Protocol Page.printToPDF."""
    port = _free_local_port()
    file_url = Path(html_path).as_uri()
    cmd = _build_cdp_edge_cmd(edge, user_data_dir, port)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ws = None
    msg_id = 0

    def send(method: str, params: dict | None = None) -> dict:
        nonlocal msg_id
        msg_id += 1
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RendererError(f"msedge CDP {method} failed: {msg['error']}")
                return msg.get("result", {})
        raise RendererError(f"msedge CDP {method} timed out")

    def read_stream(handle: str) -> bytes:
        chunks: list[bytes] = []
        while True:
            part = send("IO.read", {"handle": handle})
            data = part.get("data", "")
            if part.get("base64Encoded"):
                chunks.append(base64.b64decode(data))
            else:
                chunks.append(data.encode("utf-8"))
            if part.get("eof"):
                break
        try:
            send("IO.close", {"handle": handle})
        except Exception:
            pass
        return b"".join(chunks)

    try:
        ws_url = _wait_for_devtools_page_ws(port, min(10, timeout))
        ws = websocket.create_connection(ws_url, timeout=min(10, timeout))
        send("Page.enable")
        send("Page.navigate", {"url": file_url})

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = send("Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            value = state.get("result", {}).get("value")
            if value == "complete":
                break
            time.sleep(0.2)

        result = send("Page.printToPDF", {
            "printBackground": True,
            "displayHeaderFooter": False,
            "preferCSSPageSize": True,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "transferMode": "ReturnAsStream",
        })
        stream = result.get("stream")
        data = result.get("data")
        if stream:
            pdf_bytes = read_stream(stream)
        elif data:
            pdf_bytes = base64.b64decode(data)
        else:
            raise RendererError("msedge CDP printToPDF returned no PDF data")
        Path(pdf_path).write_bytes(pdf_bytes)
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------- Render ----------

def render(html_path: str, pdf_path: str, *, timeout: int = 300) -> None:
    """Render an HTML file to PDF via msedge headless.

    Args:
        html_path: Absolute path to a local HTML file.
        pdf_path: Absolute path where the PDF will be written.
        timeout: Seconds before the subprocess is killed.

    Raises:
        EdgeNotFoundError: If msedge.exe is not installed.
        RendererError: If the subprocess fails.
    """
    edge = find_msedge()
    if not edge:
        raise EdgeNotFoundError(
            "msedge.exe not found. Install Microsoft Edge or "
            "fall back to bundling a Chromium runtime."
        )

    html_path = str(Path(html_path).resolve())
    pdf_path = str(Path(pdf_path).resolve())
    pdf_dir = Path(os.path.dirname(pdf_path) or ".")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    file_url = Path(html_path).as_uri()
    user_data_dir = pdf_dir / f".epub2pdf-edge-{uuid.uuid4().hex}"

    cmd = [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={user_data_dir}",
        "--no-pdf-header-footer",
        "--no-margins",  # we set margins via @page CSS
        f"--print-to-pdf={pdf_path}",
        # Force a stable, deterministic render
        "--disable-extensions",
        "--disable-features=Translate",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=15000",
        file_url,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise RendererError(
            f"msedge timed out after {timeout}s"
        ) from e
    except OSError as e:
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise RendererError(f"failed to launch msedge: {e}") from e

    def output_excerpt(data: bytes | None) -> str:
        return (data or b"").decode("utf-8", errors="replace").strip()[:1200]

    def out_dir_listing() -> str:
        try:
            entries = []
            for child in sorted(pdf_dir.iterdir(), key=lambda p: p.name.lower()):
                try:
                    entries.append(f"{child.name}({child.stat().st_size})")
                except OSError:
                    entries.append(child.name)
            return ", ".join(entries[:30])
        except Exception as e:
            return f"<failed to list output dir: {e}>"

    try:
        if proc.returncode != 0:
            stderr = output_excerpt(proc.stderr)
            raise RendererError(
                f"msedge exited with code {proc.returncode}: {stderr}"
            )

        for _ in range(30):
            if os.path.isfile(pdf_path):
                break
            time.sleep(0.2)

        if not os.path.isfile(pdf_path):
            fallback_dir = pdf_dir / f".epub2pdf-edge-cdp-{uuid.uuid4().hex}"
            try:
                _cdp_print_to_pdf(
                    edge,
                    html_path,
                    pdf_path,
                    fallback_dir,
                    timeout=timeout,
                )
            except Exception as fallback_error:
                raise RendererError(
                    "msedge reported success but PDF not produced at "
                    f"{pdf_path}; stdout={output_excerpt(proc.stdout)}; "
                    f"stderr={output_excerpt(proc.stderr)}; "
                    f"out_dir={pdf_dir}; files=[{out_dir_listing()}]; "
                    f"cmd={shlex.join(str(part) for part in cmd)}; "
                    f"cdp_fallback={fallback_error}"
                ) from fallback_error
            finally:
                shutil.rmtree(fallback_dir, ignore_errors=True)
        if os.path.getsize(pdf_path) < 100:
            raise RendererError(
                f"msedge produced a suspiciously small PDF "
                f"({os.path.getsize(pdf_path)} bytes)"
            )
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)
