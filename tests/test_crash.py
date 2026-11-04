# SPDX-License-Identifier: GPL-3.0-or-later
"""Rapport de plantage et erreurs non rattrapées."""
import io
import sys
import threading

from montar import crash


def test_previous_crash_only_when_the_session_ended_badly(tmp_path):
    file = tmp_path / "traces.log"
    assert crash.previous_crash(file) == ""  # pas encore de fichier
    stream = io.StringIO()
    crash.begin_session(stream, "1.9.1")
    crash.end_session(stream)
    crash.begin_session(stream, "1.9.1")  # session fermée brutalement, sans trace
    file.write_text(stream.getvalue(), encoding="utf-8")
    assert crash.previous_crash(file) == ""
    with file.open("a", encoding="utf-8") as f:
        f.write("Windows fatal exception: access violation\n\nThread 0x1 (most recent call "
                "first):\n  File \"player.py\", line 12 in _render\n")
    report = crash.previous_crash(file)
    assert report.startswith(crash.START) and "access violation" in report
    assert "fermeture normale" not in report  # seule la dernière session
    text = crash.report(report, tmp_path / "absent.log", "1.9.1")
    assert "montar 1.9.1" in text and "player.py" in text


def test_trim_keeps_the_end(tmp_path):
    file = tmp_path / "traces.log"
    file.write_text("x" * 10 + "\n" + "y\n" * (crash.MAX_SIZE // 2 + 10), encoding="utf-8")
    crash.trim(file)
    assert file.stat().st_size <= crash.KEEP and file.read_text().startswith("y")


def test_uncaught_errors_are_recorded_not_fatal(monkeypatch):
    stream, seen = io.StringIO(), []
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    crash.install_hooks(stream, seen.append)
    try:
        raise ValueError("clip introuvable")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    worker = threading.Thread(target=lambda: 1 / 0, name="essai")
    worker.start()
    worker.join()
    text = stream.getvalue()
    assert "ValueError: clip introuvable" in text and "fil essai" in text
    assert seen == ["ValueError : clip introuvable", "ZeroDivisionError : division by zero"]
    assert crash.UNCAUGHT in text

