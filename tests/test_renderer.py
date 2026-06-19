import uuid
from pathlib import Path

import pytest

from epub2pdf.core import renderer


def test_render_uses_isolated_edge_user_data_dir(monkeypatch):
    work_dir = Path("tests_tmp/renderer_profile").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    commands = []

    class FakeProc:
        returncode = 0
        stderr = b""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(next(part.split("=", 1)[1] for part in cmd if part.startswith("--print-to-pdf="))).write_bytes(
            b"%PDF fake" + (b"0" * 128)
        )
        return FakeProc()

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "run", fake_run)

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert pdf_path.exists()
    profile_args = [part for part in commands[0] if part.startswith("--user-data-dir=")]
    assert len(profile_args) == 1
    profile_dir = Path(profile_args[0].split("=", 1)[1])
    assert profile_dir.parent == pdf_path.parent
    assert profile_dir.name.startswith(".epub2pdf-edge-")
    assert not profile_dir.exists()


def test_render_uses_fifteen_second_virtual_time_budget(monkeypatch):
    work_dir = Path(f"tests_tmp/renderer_budget_{uuid.uuid4().hex}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    commands = []

    class FakeProc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(next(part.split("=", 1)[1] for part in cmd if part.startswith("--print-to-pdf="))).write_bytes(
            b"%PDF fake" + (b"0" * 128)
        )
        return FakeProc()

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "run", fake_run)

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert "--virtual-time-budget=15000" in commands[0]
    assert "--virtual-time-budget=10000" not in commands[0]


def test_render_waits_for_pdf_after_edge_returns(monkeypatch):
    work_dir = Path(f"tests_tmp/renderer_wait_{uuid.uuid4().hex}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    sleep_calls = {"count": 0}

    class FakeProc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kwargs):
        return FakeProc()

    def fake_sleep(_):
        sleep_calls["count"] += 1
        if sleep_calls["count"] == 2:
            pdf_path.write_bytes(b"%PDF delayed" + (b"0" * 128))

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer.time, "sleep", fake_sleep)

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert sleep_calls["count"] == 2
    assert pdf_path.exists()


def test_render_missing_pdf_error_includes_edge_output(monkeypatch):
    work_dir = Path("tests_tmp/renderer_missing_pdf").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")

    class FakeProc:
        returncode = 0
        stdout = b"Printed To PDF"
        stderr = b"edge warning"

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "run", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(renderer.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        renderer,
        "_cdp_print_to_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cdp failed")),
    )

    with pytest.raises(renderer.RendererError) as exc:
        renderer.render(str(html_path), str(pdf_path), timeout=10)

    message = str(exc.value)
    assert "PDF not produced" in message
    assert "stdout=Printed To PDF" in message
    assert "stderr=edge warning" in message
    assert "out_dir=" in message
    assert "cdp_fallback=cdp failed" in message


def test_render_falls_back_to_cdp_when_edge_reports_success_without_pdf(monkeypatch):
    work_dir = Path(f"tests_tmp/renderer_cdp_{uuid.uuid4().hex}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    html_path = work_dir / "input.html"
    pdf_path = work_dir / "out.pdf"
    html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
    fallback_calls = []

    class FakeProc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_cdp(edge, html, pdf, user_data_dir, *, timeout):
        fallback_calls.append((edge, html, pdf, user_data_dir, timeout))
        Path(pdf).write_bytes(b"%PDF cdp" + (b"0" * 128))

    monkeypatch.setattr(renderer, "find_msedge", lambda: "msedge.exe")
    monkeypatch.setattr(renderer.subprocess, "run", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(renderer.time, "sleep", lambda _: None)
    monkeypatch.setattr(renderer, "_cdp_print_to_pdf", fake_cdp)

    renderer.render(str(html_path), str(pdf_path), timeout=10)

    assert pdf_path.exists()
    assert fallback_calls
    assert Path(fallback_calls[0][3]).name.startswith(".epub2pdf-edge-cdp-")


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
