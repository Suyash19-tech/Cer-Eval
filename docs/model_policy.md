# Model Policy

- Only open-weight/open-source models from non-China-origin, non-China-controlled developers.
- No hosted inference APIs. All inference local; vendor documents never leave the machine.
- Every model is listed in `models/MODEL_INVENTORY.md` with organization, country, license,
  source repo and pinned revision (+ checksums where practical) **before** use.
- Model configuration lives in one module (`app/llm/registry.py`); loading refuses any model
  id/revision not in the approved registry (no silent substitution).
- Downloads only from the official publisher org on Hugging Face via `scripts/download_approved_models.py`.
- If an approved model cannot do a task, use deterministic Python or an approved non-LLM library;
  never relax this policy for accuracy.
- Open weights ≠ open source: the exact license of each checkpoint is checked and recorded.
