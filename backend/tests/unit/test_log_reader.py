from app.services.log_reader import LogReader


def test_log_reader_limits_lines_and_redacts_secrets(tmp_path):
    (tmp_path / "app.log").write_text("x" * 5000 + "\npassword=secret token=abc", encoding="utf-8")
    result = LogReader(tmp_path).read(limit=2, max_line_length=80)
    assert len(result) == 2
    assert "secret" not in "\n".join(result)
    assert "[REDACTED]" in result[0]
    assert all(len(line) <= 80 for line in result)


def test_log_reader_reads_rotated_logs_newest_first(tmp_path):
    (tmp_path / "app.log.1").write_text("old\n", encoding="utf-8")
    (tmp_path / "app.log").write_text("new\n", encoding="utf-8")
    assert LogReader(tmp_path).read(limit=2) == ["new", "old"]
