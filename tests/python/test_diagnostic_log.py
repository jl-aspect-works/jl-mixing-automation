import json

from jl_mixing import diagnostic_log


def test_diagnostic_log_is_file_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("JL_MIXING_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("JL_MIXING_LOG_LEVEL", "debug")
    diagnostic_log.debug("test_event", operation="test.operation", completed=2)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    record = json.loads((tmp_path / "automation.jsonl").read_text(encoding="utf-8").strip())
    assert record["component"] == "automation"
    assert record["event"] == "test_event"
    assert record["operation"] == "test.operation"
    assert record["completed"] == 2


def test_info_default_filters_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("JL_MIXING_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("JL_MIXING_LOG_LEVEL", raising=False)
    diagnostic_log.debug("hidden")
    diagnostic_log.info("visible")
    lines = (tmp_path / "automation.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["visible"]


def test_sensitive_field_names_are_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("JL_MIXING_LOG_DIR", str(tmp_path))
    diagnostic_log.info("safe", token="abc", operation="test")
    record = json.loads((tmp_path / "automation.jsonl").read_text(encoding="utf-8").strip())
    assert record["token"] == "<redacted>"
    assert record["operation"] == "test"
