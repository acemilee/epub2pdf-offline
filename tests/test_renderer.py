import base64
import json
import uuid
from pathlib import Path

import pytest

from epub2pdf.core import renderer

FAKE_PDF = b"%PDF fake" + (b"0" * 128)


def _write_pdf_from_cmd(cmd, pdf_path: Path) -> None:
    Path(
        next(part.split("=", 1)[1] for part in cmd if part.startswith("--print-to-pdf="))
    ).write_bytes(FAKE_PDF)


class _FakeCliProc:
    """Stand-in for subprocess.Popen in the --print-to-pdf fallback."""

    def __init__(self, pdf_path=None, cmd=None, returncode=0, stdout=b"", stderr=b""):
        self._pdf_path = Path(pdf_path) if pdf_path is not None else None
        self._cmd = cmd
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    def communicate(self, timeout=None):
        if self._cmd is not None and self._pdf_path is not None:
            _write_pdf_from_cmd(self._cmd, self._pdf_path)
        return self._stdout, self._stderr

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class _FakePopen:
    """Stand-in for the browser process launched by the CDP path."""

    def __init__(self, *args, **kwargs):
        self.returncode = 0

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def communicate(self, timeout=None):
        return b"", b""


def test_render_uses_cdp_first_and_cleans_profile_dirs(monkeypatch):
    work_dir = Path("tests_tmp/renderer_profile").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    cdp_calls = []

    def fake_cdp(edge, html, pdf, user_data_dir, **kwargs):
        cdp_calls.append((edge, html, pdf, user_data_dir, kwargs))
        Path(pdf).write_bytes(FAKE_PDF)

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer, "_cdp_print_to_pdf", fake_cdp)
    monkeypatch.setattr(
        renderer,
        "_print_with_cli",
        lambda *args, **kwargs: pytest.fail("CLI path must not run when CDP succeeds"),
    )

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert pdf_path.exists()
    assert len(cdp_calls) == 1
    _, _, _, profile_dir, kwargs = cdp_calls[0]
    assert kwargs["generate_outline"] is True
    assert profile_dir.parent == pdf_path.parent
    assert profile_dir.name.startswith(".epub2pdf-edge-cdp-")
    assert not profile_dir.exists()


def test_render_falls_back_to_cli_when_cdp_fails(monkeypatch):
    work_dir = Path(f"tests_tmp/renderer_cli_{uuid.uuid4().hex}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    commands = []

    def fake_popen(cmd, **kwargs):
        commands.append(cmd)
        return _FakeCliProc(pdf_path, cmd)

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(
        renderer,
        "_cdp_print_to_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cdp boom")),
    )
    monkeypatch.setattr(renderer.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(renderer.time, "sleep", lambda _: None)

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert pdf_path.exists()
    assert commands, "CLI fallback should run"
    assert "--virtual-time-budget=15000" in commands[0]
    assert not any(part.startswith("--remote-debugging-port") for part in commands[0])


def test_render_error_includes_both_failure_paths(monkeypatch):
    work_dir = Path("tests_tmp/renderer_missing_pdf").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")

    class FakeProc:
        returncode = 0
        stdout = b"Printed To PDF"
        stderr = b"edge warning"

        def communicate(self, timeout=None):
            return self.stdout, self.stderr

        def poll(self):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(renderer.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        renderer,
        "_cdp_print_to_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cdp failed")),
    )

    with pytest.raises(renderer.RendererError) as exc:
        renderer.render(str(html_path), str(pdf_path), timeout=10)

    message = str(exc.value)
    assert "cdp_error=cdp failed" in message
    assert "cli_error=" in message
    assert "PDF not produced" in message
    assert "stdout=Printed To PDF" in message
    assert "stderr=edge warning" in message


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self._pending: list[str] = []

    def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)
        method = message["method"]
        if method == "Runtime.evaluate":
            result = {"result": {"type": "string", "value": "ready"}}
        elif method == "Page.printToPDF":
            result = {"data": base64.b64encode(FAKE_PDF).decode("ascii")}
        else:
            result = {}
        self._pending.append(json.dumps({"id": message["id"], "result": result}))

    def recv(self) -> str:
        return self._pending.pop(0)

    def close(self) -> None:
        pass


def test_cdp_print_requests_outline_and_waits_for_fonts_and_images(monkeypatch):
    fake_ws = _FakeWebSocket()
    pdf_path = Path("tests_tmp/renderer_cdp_print.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        renderer, "_wait_for_devtools_page_ws", lambda port, timeout, cancel_check=None: "ws://page"
    )
    monkeypatch.setattr(renderer.websocket, "create_connection", lambda *a, **k: fake_ws)
    monkeypatch.setattr(renderer.subprocess, "Popen", _FakePopen)

    renderer._cdp_print_to_pdf(
        "msedge.exe",
        "C:/tmp/input.html",
        str(pdf_path),
        Path("tests_tmp/renderer_cdp_print.pdf").parent,
        timeout=10,
        generate_outline=True,
    )

    print_calls = [m for m in fake_ws.sent if m["method"] == "Page.printToPDF"]
    assert print_calls, "Page.printToPDF was not sent"
    assert print_calls[0]["params"]["generateDocumentOutline"] is True

    evaluate_expressions = [
        m["params"]["expression"] for m in fake_ws.sent if m["method"] == "Runtime.evaluate"
    ]
    assert any("document.fonts.ready" in expr for expr in evaluate_expressions)
    assert any("document.images" in expr for expr in evaluate_expressions)
    assert pdf_path.exists()


def test_cdp_print_omits_outline_flag_when_not_requested(monkeypatch):
    fake_ws = _FakeWebSocket()
    pdf_path = Path("tests_tmp/renderer_cdp_no_outline.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        renderer, "_wait_for_devtools_page_ws", lambda port, timeout, cancel_check=None: "ws://page"
    )
    monkeypatch.setattr(renderer.websocket, "create_connection", lambda *a, **k: fake_ws)
    monkeypatch.setattr(renderer.subprocess, "Popen", _FakePopen)

    renderer._cdp_print_to_pdf(
        "msedge.exe",
        "C:/tmp/input.html",
        str(pdf_path),
        Path("tests_tmp/renderer_cdp_profile2"),
        timeout=10,
    )

    print_calls = [m for m in fake_ws.sent if m["method"] == "Page.printToPDF"]
    assert "generateDocumentOutline" not in print_calls[0]["params"]


def test_wait_for_devtools_page_ws_selects_page_target(monkeypatch):
    calls = []

    def fake_read(port, endpoint):
        calls.append((port, endpoint))
        if endpoint == "/json/version":
            return {"Browser": "Edge"}
        if endpoint == "/json/list":
            return [
                {"type": "browser", "webSocketDebuggerUrl": "ws://browser"},
                {"type": "page", "webSocketDebuggerUrl": "ws://page"},
            ]
        raise AssertionError(endpoint)

    monkeypatch.setattr(renderer, "_read_devtools_json", fake_read)

    assert renderer._wait_for_devtools_page_ws(9222, 1) == "ws://page"
    assert calls == [(9222, "/json/version"), (9222, "/json/list")]


def test_cdp_edge_cmd_allows_local_devtools_origin():
    cmd = renderer._build_cdp_edge_cmd(
        "msedge.exe",
        Path("profile"),
        11711,
    )

    assert "--remote-debugging-port=11711" in cmd
    assert "--remote-allow-origins=http://127.0.0.1:11711" in cmd


def test_render_cancelled_before_start(monkeypatch):
    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    with pytest.raises(renderer.RendererCancelled):
        renderer.render(
            "tests_tmp/renderer_cancelled.html",
            "tests_tmp/renderer_cancelled.pdf",
            timeout=10,
            cancel_check=lambda: True,
        )


def test_cli_fallback_kills_process_when_cancelled(monkeypatch):
    work_dir = Path("tests_tmp/renderer_cli_cancel").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    killed = []

    class SlowProc:
        returncode = None

        def communicate(self, timeout=None):
            import subprocess

            raise subprocess.TimeoutExpired(cmd="msedge", timeout=timeout or 0)

        def poll(self):
            return None

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(
        renderer,
        "_cdp_print_to_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cdp boom")),
    )
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *a, **k: SlowProc())
    monkeypatch.setattr(renderer.time, "sleep", lambda _: None)

    # First two checks let the CDP attempt and fallback start; then the user
    # cancels while the browser is still running.
    checks = iter([False, False, True, True, True, True])
    with pytest.raises(renderer.RendererCancelled):
        renderer.render(
            str(html_path),
            str(pdf_path),
            timeout=10,
            cancel_check=lambda: next(checks, True),
        )
    assert killed, "cancelled CLI process must be killed"
