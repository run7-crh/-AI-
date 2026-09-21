import re
from pathlib import Path


_SECRET_RE = re.compile(r"(?i)(password|token|api[_-]?key)=\S+")


class LogReader:
    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)

    def read(self, *, limit: int = 100, max_line_length: int = 4000) -> list[str]:
        limit = max(1, min(500, int(limit)))
        max_line_length = max(1, min(4000, int(max_line_length)))
        lines: list[str] = []
        rotated = [
            path for path in self.log_dir.glob("app.log.*")
            if path.name.rsplit(".", 1)[-1].isdigit()
        ]
        rotated.sort(key=lambda path: int(path.name.rsplit(".", 1)[-1]), reverse=True)
        paths = [self.log_dir / "app.log"] + rotated
        for path in paths:
            if not path.is_file():
                continue
            try:
                chunk = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in reversed(chunk):
                lines.append(_SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", line)[:max_line_length])
                if len(lines) >= limit:
                    return lines
        return lines
