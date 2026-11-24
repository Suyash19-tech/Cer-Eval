"""Download approved models at their pinned revision and verify LFS sha256 checksums.

Usage: python scripts/download_approved_models.py --role embedding [--role llm ...]
Only the official publisher repos listed in app.llm.registry are reachable; this is the
only code path allowed to touch the network for models.
Requires: pip install huggingface_hub
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.llm.registry import MODELS, ModelRole, get_model, local_model_dir  # noqa: E402

WEIGHTS_ROOT = ROOT / "models" / "weights"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(role: ModelRole) -> None:
    from huggingface_hub import HfApi, snapshot_download

    spec = get_model(role)  # runs policy checks
    target = local_model_dir(spec, WEIGHTS_ROOT)
    api = HfApi()
    info = api.model_info(spec.repo_id, revision=spec.revision, files_metadata=True)
    if info.sha != spec.revision:
        raise SystemExit(f"{spec.repo_id}: server returned {info.sha}, expected pin {spec.revision}")
    # Skip redundant runtime variants; we load safetensors via Transformers only.
    kwargs = ({"allow_patterns": list(spec.files)} if spec.files
              else {"ignore_patterns": ["onnx/*", "openvino/*", "openvino_model.*"]})
    snapshot_download(spec.repo_id, revision=spec.revision, local_dir=target, **kwargs)

    manifest: dict[str, str] = {}
    for sibling in info.siblings:
        local = target / sibling.rfilename
        if not local.is_file() or (spec.files and sibling.rfilename not in spec.files):
            continue
        digest = sha256_file(local)
        expected = sibling.lfs.sha256 if sibling.lfs else None
        if expected and digest != expected:
            raise SystemExit(f"CHECKSUM MISMATCH {spec.repo_id}/{sibling.rfilename}")
        manifest[sibling.rfilename] = digest
    (target / "CHECKSUMS.json").write_text(json.dumps(manifest, indent=2))
    print(f"OK {spec.repo_id}@{spec.revision[:8]} -> {target} ({len(manifest)} files verified)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--role", action="append", choices=[r.value for r in MODELS], required=True)
    for role in p.parse_args().role:
        download(ModelRole(role))


if __name__ == "__main__":
    main()
