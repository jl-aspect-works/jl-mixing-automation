import json

from jl_mixing import diagnostic_log


def test_diagnostic_log_is_file_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("JL_MIXING_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("JL_MIXING_LOG_LEVEL", "debug")

    diagnostic_log.debug("test_event", operation="test.operation", completed=2)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    path = tmp_path / "automation.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["component"] == "automation"
    assert record["event"] == "test_event"
    assert record["operation"] == "test.operation"
    assert record["completed"] == 2
