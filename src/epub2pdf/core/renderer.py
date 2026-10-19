"""Layer 3: Rendering Engine — msedge.exe headless wrapper.

Rendering prefers the Chrome DevTools Protocol (CDP) path because it can ask
Chromium to emit a real PDF outline (``generateDocumentOutline``) from the
document headings.  A plain ``--print-to-pdf`` CLI run is kept as a fallback
when the CDP connection cannot be established.
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
from typing import Callable, Optional

import websocket


# ---------- Errors ----------

class RendererError(Exception):
    """Base for renderer failures."""


class EdgeNotFoundError(RendererError):
    """msedge.exe could not be located."""


class RendererCancelled(RendererError):
    """Raised when the caller's ``cancel_check`` fires during rendering."""


def _check_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise RendererCancelled("render cancelled by user")


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


def _wait_for_devtools_page_ws(
    port: int,
    timeout: float,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
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
        _check_cancelled(cancel_check)
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


# Wait until fonts and images have finished loading and two animation frames
# have been painted, so printToPDF cannot capture a partially rendered page.
_READY_EXPRESSION = """
new Promise((resolve) => {
  const afterPaint = () => requestAnimationFrame(() => requestAnimationFrame(() => resolve('ready')));
  const fontsReady = () => (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
  const imagesReady = () => Promise.all(
    Array.from(document.images).map((img) => {
      if (img.complete) return Promise.resolve();
      return new Promise((res) => {
        img.addEventListener('load', res, {once: true});
        img.addEventListener('error', res, {once: true});
      });
    })
  );
  const allReady = () => imagesReady().then(fontsReady).then(afterPaint);
  if (document.readyState === 'complete') {
    allReady();
  } else {
    window.addEventListener('load', allReady, {once: true});
  }
})
"""


def _cdp_print_to_pdf(
    edge: str,
    html_path: str,
    pdf_path: str,
    user_data_dir: Path,
    *,
    timeout: int,
    generate_outline: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Render via Chrome DevTools Protocol ``Page.printToPDF``."""
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
            _check_cancelled(cancel_check)
            msg = json.loads(ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RendererError(f"msedge CDP {method} failed: {msg['error']}")
                return msg.get("result", {})
        raise RendererError(f"msedge CDP {method} timed out")

    def evaluate(expression: str, *, await_promise: bool = False) -> object:
        result = send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        if result.get("exceptionDetails"):
            raise RendererError(f"msedge CDP evaluation failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

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
        ws_url = _wait_for_devtools_page_ws(port, min(10, timeout), cancel_check)
        ws = websocket.create_connection(ws_url, timeout=min(30, timeout))
        send("Page.enable")
        send("Page.navigate", {"url": file_url})

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _check_cancelled(cancel_check)
            value = evaluate(_READY_EXPRESSION, await_promise=True)
            if value == "ready":
                break
            time.sleep(0.1)
        else:
            raise RendererError("msedge CDP page did not become render-ready")

        params = {
            "printBackground": True,
            "displayHeaderFooter": False,
            "preferCSSPageSize": True,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "transferMode": "ReturnAsStream",
        }
        if generate_outline:
            params["generateDocumentOutline"] = True
        result = send("Page.printToPDF", params)
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

def _print_with_cli(
    edge: str,
    html_path: str,
    pdf_path: str,
    user_data_dir: Path,
    *,
    timeout: int,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Fallback renderer using ``msedge --print-to-pdf``."""
    file_url = Path(html_path).as_uri()
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

    def output_excerpt(data: bytes | None) -> str:
        return (data or b"").decode("utf-8", errors="replace").strip()[:1200]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + timeout
    stdout = b""
    stderr = b""
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                _check_cancelled(cancel_check)
                if time.monotonic() >= deadline:
                    proc.kill()
                    proc.communicate()
                    raise RendererError(f"msedge timed out after {timeout}s")
    finally:
        if proc.poll() is None:
            proc.kill()

    if proc.returncode != 0:
        raise RendererError(
            f"msedge exited with code {proc.returncode}: {output_excerpt(stderr)}"
        )

    for _ in range(30):
        _check_cancelled(cancel_check)
        if os.path.isfile(pdf_path):
            return
        time.sleep(0.2)

    out_dir = Path(pdf_path).parent
    try:
        listing = ", ".join(
            sorted(
                f"{child.name}({child.stat().st_size})"
                for child in out_dir.iterdir()
                if child.is_file()
            )[:30]
        )
    except Exception as e:  # pragma: no cover - diagnostics only
        listing = f"<failed to list output dir: {e}>"
    raise RendererError(
        "msedge reported success but PDF not produced at "
        f"{pdf_path}; stdout={output_excerpt(stdout)}; "
        f"stderr={output_excerpt(stderr)}; out_dir={out_dir}; "
        f"files=[{listing}]; cmd={shlex.join(str(part) for part in cmd)}"
    )


def _pdf_ready(pdf_path: str) -> bool:
    return os.path.isfile(pdf_path) and os.path.getsize(pdf_path) >= 100


def render(
    html_path: str,
    pdf_path: str,
    *,
    timeout: int = 300,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Render an HTML file to PDF via msedge headless.

    The CDP path is tried first because it can generate a PDF outline from the
    document headings.  When CDP fails the CLI ``--print-to-pdf`` path is used
    as a fallback (without an outline; the assembler can rebuild a flat outline
    from the invisible anchors embedded by the normalizer).

    Args:
        html_path: Absolute path to a local HTML file.
        pdf_path: Absolute path where the PDF will be written.
        timeout: Total budget in seconds for both attempts.
        cancel_check: Optional callable polled while the browser runs; when it
            returns True, :class:`RendererCancelled` is raised.

    Raises:
        EdgeNotFoundError: If msedge.exe is not installed.
        RendererCancelled: If ``cancel_check`` returned True.
        RendererError: If both rendering paths fail.
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

    _check_cancelled(cancel_check)

    deadline = time.monotonic() + timeout
    cdp_error: Exception | None = None
    cdp_dir = pdf_dir / f".epub2pdf-edge-cdp-{uuid.uuid4().hex}"
    cdp_budget = max(20, min(120, timeout // 2))
    try:
        _cdp_print_to_pdf(
            edge,
            html_path,
            pdf_path,
            cdp_dir,
            timeout=cdp_budget,
            generate_outline=True,
            cancel_check=cancel_check,
        )
    except RendererCancelled:
        raise
    except Exception as e:  # CDP is best-effort; fall back to the CLI path
        cdp_error = e
        try:
            if os.path.isfile(pdf_path):
                os.remove(pdf_path)
        except OSError:
            pass
    finally:
        shutil.rmtree(cdp_dir, ignore_errors=True)

    if _pdf_ready(pdf_path):
        return

    _check_cancelled(cancel_check)
    remaining = max(20, int(deadline - time.monotonic()))
    cli_dir = pdf_dir / f".epub2pdf-edge-{uuid.uuid4().hex}"
    try:
        _print_with_cli(
            edge,
            html_path,
            pdf_path,
            cli_dir,
            timeout=remaining,
            cancel_check=cancel_check,
        )
    except RendererCancelled:
        raise
    except Exception as cli_error:
        raise RendererError(
            "msedge rendering failed via both CDP and the CLI; "
            f"cdp_error={cdp_error}; cli_error={cli_error}"
        ) from cli_error
    finally:
        shutil.rmtree(cli_dir, ignore_errors=True)

    if not _pdf_ready(pdf_path):
        size = os.path.getsize(pdf_path) if os.path.isfile(pdf_path) else 0
        raise RendererError(f"msedge produced a suspiciously small PDF ({size} bytes)")
