import pytest

from app.llm.registry import (
    MODELS, ModelPolicyError, ModelRole, ModelSpec, assert_policy, get_model, require_approved,
)


def test_all_registered_models_pass_policy():
    for role in ModelRole:
        spec = get_model(role)
        assert spec.license == "Apache-2.0" and spec.country == "USA"


def test_alt_llm_not_production():
    assert MODELS[ModelRole.LLM_ALT].approved_for_production is False


@pytest.mark.parametrize("repo", [
    "Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3", "BAAI/bge-m3", "THUDM/glm-4-9b",
    "ibm-granite/../Qwen", "unknown-org/model",
])
def test_prohibited_or_unapproved_rejected(repo):
    spec = ModelSpec(role=ModelRole.LLM, repo_id=repo, revision="a" * 40,
                     organization="x", country="x", license="x")
    with pytest.raises(ModelPolicyError):
        assert_policy(spec)


def test_branch_name_revision_rejected():
    spec = ModelSpec(role=ModelRole.LLM, repo_id="ibm-granite/granite-3.3-8b-instruct",
                     revision="main", organization="IBM", country="USA", license="Apache-2.0")
    with pytest.raises(ModelPolicyError):
        assert_policy(spec)


def test_require_approved_enforces_pin():
    llm = get_model(ModelRole.LLM)
    assert require_approved(llm.repo_id, llm.revision) == llm
    with pytest.raises(ModelPolicyError):
        require_approved(llm.repo_id, "b" * 40)
    with pytest.raises(ModelPolicyError):
        require_approved("meta-llama/Llama-3-8B", "a" * 40)
