# API

Base path `/api`. Errors: `{"error": {"code", "message", "details"}}`.

| Method | Path | Phase | Status |
|---|---|---|---|
| GET | /health | 1 | implemented |
| POST | /evaluations | 3–4 | planned |
| POST | /evaluations/{id}/requirements/confirm | 4 | planned |
| POST | /evaluations/{id}/vendors | 3 | planned |
| POST | /evaluations/{id}/run | 8 | planned |
| GET | /evaluations/{id}/status | 8 | planned |
| GET | /evaluations/{id}/certification-report | 7 | planned |
| GET | /evaluations/{id}/vendors | 6 | planned |
| GET | /evaluations/{id}/results | 9 | planned |
| GET | /evaluations/{id}/reports/{report_type} | 7 | planned |
| POST | /reviews/{review_id}/decision | 6 | planned |

## Vendors and screening (Phase 6)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/evaluations/{id}/vendors` | multipart `name` + `files[]` (PDF/image/ZIP). 409 until requirements are confirmed. Documents are extracted, classified and indexed into that vendor's own RAG index. |
| POST | `/api/evaluations/{id}/vendors/{vid}/screen?as_of=YYYY-MM-DD` | 202; background screening. `as_of` defaults to today. |
| GET | `/api/evaluations/{id}/vendors/{vid}` | documents, compliance-matrix findings, eligibility (PASS / FAIL / PENDING_HUMAN_REVIEW). |
| POST | `/api/evaluations/{id}/vendors/{vid}/review` | `X-Reviewer-Token`. Resolves one NEEDS_HUMAN_REVIEW finding; reason >= 10 chars; audited; gate recomputed. |

## Reports (Phase 7)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/evaluations/{id}/reports/certification` | Generates a fresh 11-sheet `.xlsx` from persisted findings (also saved under `data/reports/<id>/`) and audits it. Works before and after human review; unscreened vendors show NOT SCREENED. |

Sheets: Executive Summary, Vendor Overview, X/Y/Z Certification Compliance, All Certifications, Missing Certificates,
Expired Certificates, Mismatches, Human Review Required, Evidence References. All vendor-controlled text is neutralised
against Excel formula injection.

## Workflow (Phase 8)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/evaluations/{id}/workflow/start?as_of=` | 202; runs the graph in the background. 409 if already started; failures set `workflow_status=FAILED` + `error`. |
| GET | `/api/evaluations/{id}/workflow` | status, `awaiting_human_review`, `pending_review`, per-vendor results, node log, report paths. |
| POST | `/api/evaluations/{id}/workflow/resume` | `X-Reviewer-Token`; 409 unless waiting for review. Decisions must already be recorded via the review endpoint. |

## Technical and commercial evaluation (Phase 9)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/evaluations/{id}/criteria/extract` | 202; Granite proposes grounded technical/commercial criteria from the tender (409 until certification requirements are confirmed). |
| GET | `/api/evaluations/{id}/criteria` | criteria, flags, `criteria_status`, `config`. |
| POST | `/api/evaluations/{id}/criteria` | `X-Reviewer-Token`. Add a criterion extraction missed (only while `PENDING_CONFIRMATION`). `supporting_text` must appear verbatim in the tender (else 422); `reason` is audited; origin `HUMAN`; confirmed with the rest. |
| POST | `/api/evaluations/{id}/criteria/confirm` | `X-Reviewer-Token`. Accept/edit/reject (flagged items need a decision; reject needs a reason), set weights and `config` (order, dependency, min score, stage weights). |
| POST | `/api/evaluations/{id}/vendors/{vid}/criteria/review` | `X-Reviewer-Token`. Resolves a NEEDS_HUMAN_REVIEW / MISSING_DETAIL finding (MEETS/DEVIATES + reason). Only for certification-qualified vendors. |
| POST | `/api/evaluations/{id}/vendors/{vid}/commercial/approve` | `X-Reviewer-Token`. Clears the review flag on a commercial summary with a reason. |
| GET | `/api/evaluations/{id}/results` | per-vendor certification / technical / commercial status, scores, ranking. Non-qualified vendors show `NOT_EVALUATED`. |
| GET | `/api/evaluations/{id}/reports/{technical,commercial,consolidated}` | `.xlsx` downloads. |

## UI support endpoints (Phase 10)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/evaluations` | Dashboard rows with vendor / pass / fail / pending counts. |
| GET | `/api/evaluations/{id}/vendors` | All vendors with documents and certification findings. |
| GET | `/api/evaluations/{id}/vendors/{vid}/documents/{did}/file` | Original document for review (pdf/png/jpg only, vendor-scoped, path confined to the vendor's upload folder, `nosniff`). |
| GET | `/api/evaluations/{id}/evaluation-details` | Technical/commercial findings and commercial summaries (qualified vendors only). |
| POST | `/api/evaluations/{id}/workflow/retry` | `X-Reviewer-Token`. Continue from the last checkpoint after a failed node. |
