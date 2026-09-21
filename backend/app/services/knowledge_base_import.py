import os
import uuid
from pathlib import Path


class ImportValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class KnowledgeBaseImportService:
    def __init__(self, data_dir: str | Path, *, max_file_bytes: int = 10 * 1024 * 1024, max_files: int = 20):
        self.data_dir = Path(data_dir)
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files

    def validate(self, name: str, payload: bytes) -> None:
        if not name or Path(name).name != name or ".." in name or "/" in name or "\\" in name:
            raise ImportValidationError("unsafe_filename")
        if Path(name).suffix.lower() != ".md":
            raise ImportValidationError("markdown_only")
        if len(payload) > self.max_file_bytes:
            raise ImportValidationError("file_too_large")

    def import_files(self, files: list[tuple[str, bytes]]) -> list[str]:
        if not files:
            raise ImportValidationError("no_files")
        names = [name.casefold() for name, _ in files]
        if len({name.casefold() for name in names}) != len(names):
            raise ImportValidationError("duplicate_filename")
        if len(files) > self.max_files:
            raise ImportValidationError("too_many_files")
        for name, payload in files:
            self.validate(name, payload)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        try:
            for name, payload in files:
                target = self.data_dir / name
                temp = self.data_dir / f"{name}.tmp-{uuid.uuid4().hex}"
                try:
                    with open(temp, "wb") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp, target)
                except Exception:
                    try:
                        temp.unlink()
                    except FileNotFoundError:
                        pass
                    raise
                written.append(name)
        except Exception:
            raise
        return written
