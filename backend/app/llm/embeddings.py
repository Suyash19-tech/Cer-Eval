"""Local Granite embedding model. Loads only from the pinned, pre-downloaded directory."""

from pathlib import Path

from app.core.config import get_settings
from app.llm.registry import ModelRole, get_model, local_model_dir, require_approved

_DEFAULT_WEIGHTS = Path(__file__).resolve().parents[3] / "models" / "weights"


class GraniteEmbedder:
    def __init__(self, weights_root: Path = _DEFAULT_WEIGHTS) -> None:
        import os

        if get_settings().offline:  # never reach the network at runtime
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        spec = get_model(ModelRole.EMBEDDING)
        require_approved(spec.repo_id, spec.revision)
        path = local_model_dir(spec, weights_root)
        if not (path / "model.safetensors").is_file():
            raise FileNotFoundError(f"Approved model not downloaded: run scripts/download_approved_models.py ({path})")
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(str(path), device="cpu")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()
