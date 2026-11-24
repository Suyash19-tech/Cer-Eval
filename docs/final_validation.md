# Final Validation (Phase 12)

## Automated checks (run 2026-11-24)
- Backend: `pytest` -> 141 passed, 5 skipped (skipped = opt-in real-model tests, `HAL_RUN_LLM_TESTS=1`).
- Real-model end-to-end (`pytest -m llm tests/test_integration_live.py`), run at the end of Phase 11: passed (~4 min).
- Frontend: `tsc --noEmit`, `npm run lint`, `npm run build` clean.
- Policy audit: only mentions of prohibited model families are the blocklist in `app/llm/registry.py`, its test, and the docs.
  No outbound HTTP client in `backend/app`; HF offline mode forced; LangSmith tracing forced off.

## Checklist
| Requirement | Evidence |
|---|---|
| Certification screening before evaluation | workflow graph, `test_workflow.py` |
| Hard gate; failed vendors never downstream | `GateViolation` re-check, dataset test (B, D never evaluated) |
| LLM cannot declare compliance | deterministic `validator.py`/`gate.py`; quotes must appear verbatim |
| Ambiguity -> human review | vendor E PENDING; reviewer token + audit log |
| Vendor isolation | FK scoping, per-vendor vector store, `VendorIsolationError` tests |
| Local, approved models only, pinned | `registry.py`, `models/MODEL_INVENTORY.md`, `test_model_registry.py` |
| Synthetic data labelled | stamp on every page, tested |
| Reports (certification, technical, commercial, consolidated) | `test_report.py`, integration test |

## Deployment checks (Phase 12 follow-up)
- `docker compose build` and `up` work (postgres, backend, frontend). Backend health OK on Postgres 16; all 10 tables created;
  an evaluation upload was accepted; the frontend proxy reaches the backend.
- Found and fixed: `threading.Lock | None` annotations crashed on Python 3.12 (container) though fine on 3.14 (local);
  docTR needed `libgl1`/`libglib2.0-0` in the image. Tesseract and docTR both read a scanned certificate in the container.
- Postgres: the whole suite (141 passed, 5 skipped) also passes on Postgres 16 via `HAL_TEST_DATABASE_URL=postgresql+psycopg://...`,
  including the five-vendor dataset workflow with scripted LLM. This found a real bug: the vendor-screen and evaluation-create
  routes queued a background task before committing, so the task could wait on the request's row lock or not see the row.
  Both now commit first.
- NOT verified in Docker: Granite inference (CPU only in Docker Desktop, 3.3 GB model, slow), and truly concurrent
  multi-vendor writes on Postgres with the real model.

## Known limitations (not verified / not done)
- Granite in Docker untested.
- Tesseract not installed locally (docTR fallback used); docTR weights are bundled and sha256-checked in `models/weights/ocr/`.
- Granite Vision pinned, not downloaded. 8B criteria extraction is nondeterministic; humans confirm criteria.
- Live test used a scripted reviewer and synthetic documents only; reliability on real tenders is unmeasured.
- Manual add-criterion API is tested; its UI form passes typecheck/lint/build but was not exercised in a browser. No LICENSE file (project licence is the owner's choice).
- Model-card text was not read line by line; licences come from the Hugging Face API.
