# Architecture

Seven layers; dependencies point downward only.

1. **Presentation** – Next.js/TypeScript/Tailwind dashboard (Phase 10).
2. **API & services** – FastAPI thin routes → service classes → repositories (SQLAlchemy).
3. **Document intelligence** – PDF text, OCR fallback, page-level provenance, classification.
4. **RAG** – chunking, Granite embeddings, FAISS; every chunk carries `vendor_id`; one index
   per (evaluation, vendor) so cross-vendor retrieval is impossible by construction.
5. **LangGraph orchestration** – typed state, per-vendor subgraphs, checkpointed human review.
6. **Deterministic evaluation** – certificate validation and the eligibility gate are plain
   Python. LLMs extract and cite; they never decide compliance.
7. **Reporting** – OpenPyXL workbooks (certification first, then technical/commercial/final).

## Key decisions
- **LLM extracts, Python decides.** Extraction output is Pydantic-validated with evidence text;
  a field whose evidence quote is not found in the source page is nulled and the requirement is
  routed to human review. This is also the main prompt-injection defence: document text can
  only ever populate data fields.
- **Vendor isolation in three places:** DB (`vendor_id` NOT NULL + FKs), RAG (separate index
  per vendor), graph (per-vendor `Send` payloads).
- **Hard gate in structure:** see `langgraph_workflow.md`.
- **SQLite for dev/tests, PostgreSQL in Compose.** FAISS for vectors (pgvector deferred; the
  vector store sits behind a small interface so it can be swapped).
- **Offline by default** (`HAL_OFFLINE=true`): model loading uses local, revision-pinned paths.
- **Dependencies are added per phase** to avoid unused packages.

## Roadmap
P1 foundation (done) → P2 model infra → P3 document intelligence → P4 tender requirements →
P5 RAG → P6 screening/gate/review → P7 certification Excel → P8 LangGraph → P9 technical &
commercial → P10 frontend → P11 synthetic 5-vendor integration → P12 final validation.

## RAG (Phase 5)
`app/rag/`: `chunker.py` (page-aware chunks, <=900 chars, 150 overlap, never cross pages, carry document/vendor/page/category),
`vector_store.py` (`VectorStore` protocol + exact-cosine `FaissVectorStore`, persisted as `index.faiss` + `chunks.json`),
`service.py` (`RagService`). Isolation: one physical index per `(evaluation_id, vendor_id)` at
`data/rag/<evaluation>/<vendor>/`; no cross-vendor search API exists; IDs are validated against `[A-Za-z0-9_-]{1,64}`;
every hit is re-checked for the requested vendor (`VendorIsolationError`). Scores are retrieval hints, never proof:
with the real Granite embedder an ISO 14001 certificate scored 0.82 against an "AS9100 aerospace" query (vs 0.87 for the
true match), so Phase 6 must validate cited text deterministically.

## Certificate screening (Phase 6)
`app/screening/` + `app/services/vendor_service.py`. Per vendor and confirmed requirement: (1) deterministic scan - if the
required standard is not mentioned anywhere in the vendor's documents the finding is MISSING; (2) vendor-scoped RAG retrieval
and Granite proposes certificate quotes; (3) Python verifies each quote verbatim, then decides the status (holder match,
evidence from a certificate-class document only, revision/year, parsed expiry vs `as_of`, "N months remaining" rules);
(4) best candidate wins; (5) `decide_eligibility`: any mandatory MISSING/EXPIRED/MISMATCH -> FAIL, else any
NEEDS_HUMAN_REVIEW -> PENDING_HUMAN_REVIEW, else PASS. Optional requirements never block. Eligibility conditions that are
not machine-checkable become NEEDS_HUMAN_REVIEW findings. A screening crash sets FAILED and clears eligibility.

## Technical & commercial evaluation (Phase 9) - `app/evaluation/`
Entry only via the workflow's PASS branch (nodes re-check eligibility in the DB). Tender criteria are LLM-proposed, verified
verbatim against the tender (value/unit must appear in the quote; deterministic gap-fillers for value, unit, comparator,
commercial parameter; certification sentences are dropped), then human-confirmed with weights and an `EvaluationConfig`
(order technical_first / commercial_first / independent, second-stage dependency, minimum technical score, stage weights).
Per criterion Granite only quotes the vendor sentence; Python parses numbers/units (with conversion), compares, and sets
MEETS / DEVIATES / MISSING_DETAIL / NEEDS_HUMAN_REVIEW. Unit mismatch, ambiguity or conflicting statements -> human.
Commercial: quoted fields are verified verbatim, amounts/durations parsed deterministically, price components reconciled
(qty x unit (+charges/taxes) vs total); missing data stays null. Vendor status: QUALIFIED/NOT_QUALIFIED/NEEDS_REVIEW
(technical), VALID/NOT_QUALIFIED/NEEDS_REVIEW (commercial). Ranking: only certification PASS + technical QUALIFIED +
commercial VALID, single currency; combined = w_t x technical score + w_c x price score (L1: cheapest = 100).

## Vector store choice (Phase 11 finding)
The default store is `NumpyVectorStore` (exact cosine, identical results to `IndexFlatIP`). FAISS and PyTorch each bundle
libomp; loading both in one process aborts with "OMP: Error #15" or hangs on macOS, and the backend uses PyTorch for Granite
embeddings and docTR OCR. FAISS remains available via `HAL_VECTOR_STORE=faiss` (tests set `KMP_DUPLICATE_LIB_OK=TRUE`, an
unsupported workaround, to exercise both). Both are behind the `VectorStore` protocol.
