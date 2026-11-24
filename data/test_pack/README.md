# Test pack: 1 tender + 3 vendors (SYNTHETIC)

Every page states `SYNTHETIC — NOT VALID FOR PROCUREMENT`. Regenerate with `python scripts/generate_test_pack.py`.

| Vendor | Files | Expected |
|---|---|---|
| V1 Meridian | 3 certificate PDFs, technical + commercial quotation, profile | PASS, QUALIFIED, rank 1 |
| V2 Orion | 3 certificate PDFs (ISO 14001 expired), 2 quotations | FAIL, never evaluated (cheapest price, ignored) |
| V3 Vertex | 2 scanned certificates + 1 text cert, 2 quotations, profile; also supplied as one ZIP | PASS via OCR, QUALIFIED, rank 2 |

Upload the tender, then add each vendor with all files in its folder (V3: either the folder files or the ZIP, not both).
Ground truth: `expected_results.json`.
