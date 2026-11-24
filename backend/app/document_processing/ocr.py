"""OCR backends behind one small interface. Both are local, permissively licensed (Apache-2.0)."""

import hashlib
import shutil
from pathlib import Path
from typing import Protocol

from PIL import Image


class OcrEngine(Protocol):
    name: str

    def image_to_text(self, image: Image.Image) -> str: ...


class TesseractOcr:
    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract

        self._t = pytesseract

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def image_to_text(self, image: Image.Image) -> str:
        return self._t.image_to_string(image.convert("L"))


_OCR_WEIGHTS = Path(__file__).resolve().parents[3] / "models" / "weights" / "ocr"
# Pinned weights (sha256 recorded in models/MODEL_INVENTORY.md). Loaded from the repo; no network access.
_DOCTR_FILES = {
    "fast_base-688a8b34.pt": "688a8b3489e9f5d0290c476c6272ec3b18de3ee646c8a0dc158203b1a9c62ace",
    "crnn_vgg16_bn-0417f351.pt": "0417f3511f5c75369bdcbe06539853b9c2d170aa3baceb2acc454c775ddac087",
}


def _verified(name: str, root: Path) -> Path:
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"OCR weights missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != _DOCTR_FILES[name]:
        raise RuntimeError(f"OCR weights {name} failed sha256 check; refusing to load")
    return path


class DocTrOcr:
    name = "doctr"

    def __init__(self, weights_root: Path = _OCR_WEIGHTS) -> None:
        from doctr.models import detection, ocr_predictor, recognition

        det = detection.fast_base(pretrained=False, pretrained_backbone=False)
        det.from_pretrained(str(_verified("fast_base-688a8b34.pt", weights_root)))
        reco = recognition.crnn_vgg16_bn(pretrained=False, pretrained_backbone=False)
        reco.from_pretrained(str(_verified("crnn_vgg16_bn-0417f351.pt", weights_root)))
        self._predictor = ocr_predictor(det_arch=det, reco_arch=reco, pretrained=False)

    def image_to_text(self, image: Image.Image) -> str:
        import numpy as np

        result = self._predictor([np.asarray(image.convert("RGB"))])
        lines = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    lines.append(" ".join(w.value for w in line.words))
        return "\n".join(lines)


def get_ocr_engine() -> OcrEngine:
    """Prefer Tesseract when its binary exists, else docTR. Raises if neither works."""
    if TesseractOcr.available():
        return TesseractOcr()
    return DocTrOcr()
