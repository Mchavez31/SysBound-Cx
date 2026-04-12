import os
import re
from pathlib import Path


def _project_upload_root() -> Path:
    base = Path(__file__).resolve().parent.parent
    return base / "uploads"


def save_upload(file_content: bytes, project_id: str, filename: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9._\-]", "_", filename) or "upload.pdf"
    dest_dir = _project_upload_root() / project_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    counter = 1
    while dest_path.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest_path = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    dest_path.write_bytes(file_content)
    return str(dest_path.resolve())


def get_upload_path(project_id: str, filename: str) -> str:
    dest_dir = _project_upload_root() / project_id
    path = dest_dir / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path.resolve())


def delete_upload_file(file_path: str) -> None:
    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
