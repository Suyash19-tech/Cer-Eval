# HAL Vendor Certification Screening & Tender Evaluation

Certification screening → compliance report → hard eligibility gate → only passing vendors proceed.
All AI inference is local with approved non-China-origin open models (see `models/MODEL_INVENTORY.md`).

## Status
Phase 1 (foundation) complete. See `docs/architecture.md` for the roadmap.

## Dev quickstart
```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m pytest
cd backend && ../.venv/bin/uvicorn app.main:app --reload
```
All data produced by `scripts/generate_synthetic_data.py` is marked
**SYNTHETIC — NOT VALID FOR PROCUREMENT**.


## Synthetic five-vendor demo and integration tests
See `data/synthetic/README.md`. `scripts/generate_synthetic_data.py` builds the tender, five vendor submissions (text,
scanned, image, ZIP) and `expected_results.json`; `backend/tests/test_integration_dataset.py` runs them through the whole
system and compares against the expected file.
