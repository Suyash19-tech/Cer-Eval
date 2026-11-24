"""Upload validation (extension + magic bytes + size), filename sanitisation, safe ZIP extraction."""

import re
import zipfile
from pathlib import Path, PurePosixPath

from app.core.exceptions import ValidationFailedError

ALLOWED_TYPES: dict[str, tuple[str, bytes]] = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".zip": ("application/zip", b"PK\x03\x04"),
}
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_filename(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name  # drop any directory components
    base = _SAFE_CHARS.sub("_", base).strip(" .")
    return base[:200] or "unnamed"


def validate_upload(filename: str, head: bytes, size: int, max_bytes: int) -> str:
    """Return the verified MIME type or raise. The declared client MIME type is never trusted."""
    ext = Path(sanitize_filename(filename)).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise ValidationFailedError(f"File type '{ext}' is not allowed", {"allowed": sorted(ALLOWED_TYPES)})
    if size <= 0:
        raise ValidationFailedError("File is empty")
    if size > max_bytes:
        raise ValidationFailedError(f"File exceeds {max_bytes} bytes")
    mime, magic = ALLOWED_TYPES[ext]
    if not head.startswith(magic):
        raise ValidationFailedError(f"File content does not match extension '{ext}'")
    return mime


def safe_extract_zip(
    zip_path: Path, dest: Path, *, max_entries: int, max_uncompressed_bytes: int, max_entry_bytes: int
) -> list[Path]:
    """Extract only allowed file types; reject traversal, symlinks, nested archives and zip bombs."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ValidationFailedError("Corrupt ZIP archive") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_entries:
            raise ValidationFailedError(f"ZIP has more than {max_entries} entries")
        if sum(i.file_size for i in infos) > max_uncompressed_bytes:
            raise ValidationFailedError("ZIP uncompressed size exceeds limit")
        for info in infos:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValidationFailedError(f"Symlink entry rejected: {info.filename}")
            if info.file_size > max_entry_bytes:
                raise ValidationFailedError(f"Entry too large: {info.filename}")
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if info.filename.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise ValidationFailedError(f"Unsafe path in ZIP: {info.filename}")
            ext = Path(parts[-1]).suffix.lower()
            if ext == ".zip":
                raise ValidationFailedError("Nested ZIP archives are not allowed")
            if ext not in ALLOWED_TYPES:
                continue  # unsupported members are skipped, and reported by the caller via diff
            target = (dest / sanitize_filename(parts[-1])).resolve()
            if dest not in target.parents:
                raise ValidationFailedError(f"Unsafe path in ZIP: {info.filename}")
            target = _unique(target)
            written = 0
            with zf.open(info) as src, target.open("wb") as out:  # stream with a hard cap
                while chunk := src.read(1 << 16):
                    written += len(chunk)
                    if written > max_entry_bytes:
                        target.unlink(missing_ok=True)
                        raise ValidationFailedError(f"Entry exceeds size limit: {info.filename}")
                    out.write(chunk)
            extracted.append(target)
    return extracted


def _unique(path: Path) -> Path:
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate
