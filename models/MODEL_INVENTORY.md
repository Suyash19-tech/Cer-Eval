# Model Inventory

**Status:** revisions pinned and licenses read from the Hugging Face API; downloaded models are
sha256-verified (see Status column). Official model cards have not been read line by line. A model must never be swapped without editing
this file and the central model registry (`backend/app/llm/registry.py`, Phase 2).

| Role | Model (candidate) | Organization | Country | License (to verify) | Source | Revision | Status |
|---|---|---|---|---|---|---|---|
| Primary LLM | `ibm-granite/granite-3.3-8b-instruct` | IBM | USA | Apache-2.0 (HF API) | Hugging Face official `ibm-granite` org | `51dd4bc2ade4059a6bd87649d68aa11e4fb2529b` | PINNED, full-precision not downloaded (~16 GB; for GPU hosts) |
| Primary LLM (local, quantised) | `ibm-granite/granite-3.3-8b-instruct-GGUF` file `granite-3.3-8b-instruct-Q4_K_M.gguf` (IBM-published) | IBM | USA | Apache-2.0 (HF API) | Hugging Face `ibm-granite` org | `e40e9dd739c7be00fa965c16ce167088190ce114` | **DOWNLOADED, sha256 verified (77bcee06…), offline schema-constrained JSON extraction tested; ~3.3 GB peak RSS, ~27 s for first short extraction incl. warm-up** |
| Document vision | `ibm-granite/granite-vision-3.3-2b` | IBM | USA | Apache-2.0 (HF API) | Hugging Face `ibm-granite` org | `bf66a8244401a8e26d2ff429aa82df8550a289e5` | PINNED, not downloaded |
| Embeddings | `ibm-granite/granite-embedding-311m-multilingual-r2` | IBM | USA | Apache-2.0 (HF API) | Hugging Face `ibm-granite` org | `44399559930365213510b1ee2eb15ded83374f0e` | **DOWNLOADED, sha256-verified, offline inference tested** (768-dim); `model.safetensors` sha256 `dcb6431b…10d31` |
| Alt LLM (benchmark only) | `allenai/Olmo-3-7B-Instruct` | Allen Institute for AI | USA | Apache-2.0 (HF API) | Hugging Face `allenai` org | `6e5971d9eba42665f5bd5a0fcf047f299ce1dccc` | PINNED, benchmark only |

## Prohibited
DeepSeek, Qwen/Alibaba, GLM/Zhipu, Baidu ERNIE, Moonshot/Kimi, Yi/01.AI, InternLM, MiniMax,
PaddleOCR, BAAI BGE, any other China-origin or China-controlled model/service, and any hosted
inference API (OpenAI, Gemini, Anthropic, etc.).

## Python dependency licences (checked Phase 12 via `pip show`)
langgraph 1.2.24 MIT; langgraph-checkpoint-sqlite 3.1.3 MIT; langchain-core 1.8.4 MIT; langsmith 0.16.0 MIT
(tracing forced off, no network use); openpyxl 3.1.5 MIT; python-doctr 1.1.0 Apache-2.0; llama-cpp-python 0.3.38 MIT;
faiss-cpu 1.16.0 MIT (opt-in); pypdfium2 5.15.2 BSD-3/Apache-2.0; reportlab 5.1.0 BSD. PyMuPDF (AGPL) is not used.

## Non-LLM components (original Phase 3 review)
Tesseract (Apache-2.0, Google/HP origin), docTR (Apache-2.0, Mindee, France), Docling (MIT, IBM),
PyMuPDF (**AGPL-3.0 / commercial** – legal review required before use; `pypdfium2` is a
permissive fallback), FAISS (MIT, Meta).

## Notes
- Ollama is installed on this machine but is **not** part of the approved stack; models served
  through it would bypass revision pinning. It will not be used.
- Required hardware: Granite 3.3 8B needs ~16 GB in bf16. This dev machine has 16 GB RAM
  (Apple Silicon), so quantised inference (llama.cpp GGUF) or a smaller test configuration will be
  needed locally; Phase 2 documents what actually runs.

## OCR model weights (docTR, Mindee – France, Apache-2.0 library)
Fetched once from `doctr-static.mindee.com` (publisher's host) into `~/.cache/doctr/models`; **not
yet bundled/pinned in-repo**. Observed sha256:
- `fast_base-688a8b34.pt` `688a8b3489e9f5d0290c476c6272ec3b18de3ee646c8a0dc158203b1a9c62ace` (text detection)
- `crnn_vgg16_bn-0417f351.pt` `0417f3511f5c75369bdcbe06539853b9c2d170aa3baceb2acc454c775ddac087` (recognition)

The weights are now copied to `models/weights/ocr/` and loaded by `DocTrOcr` with `pretrained=False`; sha256 is
checked before loading and a mismatch refuses to load. Verified offline with `~/.cache/doctr` removed. The weights' own
license has not been verified separately from the library license (Apache-2.0) - still TODO. Tesseract is preferred
when installed (it is in the Docker image).
