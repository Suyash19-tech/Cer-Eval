# Security Notes

Implemented in Phase 1: central settings (no hardcoded secrets), JSON structured logging, audit
log table, consistent error envelope, human-review tokens read from env (empty by default → no
one can approve), SQLite FK enforcement.

Planned (with the phase that adds them): extension+MIME+magic-byte validation and size limits
(P3), safe ZIP extraction with path-traversal / zip-bomb / entry-count limits (P3), sanitised
filenames and per-evaluation upload directories (P3), prompt-injection handling – document text
is always passed as quoted data, outputs schema-validated, evidence must be found verbatim in
source (P4/P6), reviewer authentication on review endpoints (P6), safe download endpoints with
whitelisted report types (P7).

Limitation: certificate authenticity is **not** verified against issuing authorities.
