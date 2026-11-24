"""Central, immutable registry of approved models. The ONLY place model ids/revisions live.

Loading any model not listed here, or at a different revision, is refused (no silent swaps).
Revisions were verified against the Hugging Face API on 2026-11-23 (license=apache-2.0,
not gated, official publisher org). Re-verify and update docs/MODEL_INVENTORY.md when changing.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import AppError

# Publishers allowed to appear in the registry (origin verified: IBM - USA, Ai2 - USA).
APPROVED_ORGS: frozenset[str] = frozenset({"ibm-granite", "allenai"})

# Defence in depth: substrings that must never appear in a model id/org.
PROHIBITED_MARKERS: tuple[str, ...] = (
    "deepseek", "qwen", "alibaba", "glm", "zhipu", "thudm", "ernie", "baidu", "paddle",
    "moonshot", "kimi", "01-ai", "yi-", "internlm", "internvl", "minimax", "baai", "bge-",
    "openbmb", "minicpm", "tencent", "hunyuan", "bytedance",
)


class ModelRole(StrEnum):
    LLM = "llm"
    VISION = "vision"
    EMBEDDING = "embedding"
    LLM_ALT = "llm_alt"
    LLM_GGUF = "llm_gguf"  # IBM-published quantised build of the primary LLM (local dev / CPU / Metal)


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ModelRole
    repo_id: str
    revision: str  # full commit SHA, never a branch name
    organization: str
    country: str
    license: str
    approved_for_production: bool = True  # False => benchmarking candidate only
    files: tuple[str, ...] = ()  # if set, download only these files

    @property
    def org(self) -> str:
        return self.repo_id.split("/", 1)[0]


MODELS: dict[ModelRole, ModelSpec] = {
    ModelRole.LLM: ModelSpec(
        role=ModelRole.LLM, repo_id="ibm-granite/granite-3.3-8b-instruct",
        revision="51dd4bc2ade4059a6bd87649d68aa11e4fb2529b",
        organization="IBM", country="USA", license="Apache-2.0"),
    ModelRole.VISION: ModelSpec(
        role=ModelRole.VISION, repo_id="ibm-granite/granite-vision-3.3-2b",
        revision="bf66a8244401a8e26d2ff429aa82df8550a289e5",
        organization="IBM", country="USA", license="Apache-2.0"),
    ModelRole.EMBEDDING: ModelSpec(
        role=ModelRole.EMBEDDING, repo_id="ibm-granite/granite-embedding-311m-multilingual-r2",
        revision="44399559930365213510b1ee2eb15ded83374f0e",
        organization="IBM", country="USA", license="Apache-2.0"),
    ModelRole.LLM_GGUF: ModelSpec(
        role=ModelRole.LLM_GGUF, repo_id="ibm-granite/granite-3.3-8b-instruct-GGUF",
        revision="e40e9dd739c7be00fa965c16ce167088190ce114",
        organization="IBM", country="USA", license="Apache-2.0",
        files=("granite-3.3-8b-instruct-Q4_K_M.gguf",)),
    ModelRole.LLM_ALT: ModelSpec(
        role=ModelRole.LLM_ALT, repo_id="allenai/Olmo-3-7B-Instruct",
        revision="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc",
        organization="Allen Institute for AI", country="USA", license="Apache-2.0",
        approved_for_production=False),
}


class ModelPolicyError(AppError):
    status_code = 500
    code = "model_policy_violation"


def assert_policy(spec: ModelSpec) -> None:
    """Raise if a spec violates the origin/organization policy."""
    lowered = spec.repo_id.lower()
    for marker in PROHIBITED_MARKERS:
        if marker in lowered:
            raise ModelPolicyError(f"{spec.repo_id} matches prohibited marker '{marker}'")
    if spec.org not in APPROVED_ORGS:
        raise ModelPolicyError(f"Organization '{spec.org}' is not approved")
    if len(spec.revision) != 40 or any(c not in "0123456789abcdef" for c in spec.revision):
        raise ModelPolicyError(f"{spec.repo_id}: revision must be a full 40-char commit SHA")


def get_model(role: ModelRole) -> ModelSpec:
    spec = MODELS[role]
    assert_policy(spec)
    return spec


def require_approved(repo_id: str, revision: str) -> ModelSpec:
    """Gate used by every loader: id AND revision must match the registry exactly."""
    for spec in MODELS.values():
        if spec.repo_id == repo_id:
            assert_policy(spec)
            if spec.revision != revision:
                raise ModelPolicyError(f"{repo_id}: revision {revision} is not the approved pin")
            return spec
    raise ModelPolicyError(f"{repo_id} is not in the approved model registry")


def local_model_dir(spec: ModelSpec, weights_root: Path) -> Path:
    return weights_root / spec.role.value / spec.revision
