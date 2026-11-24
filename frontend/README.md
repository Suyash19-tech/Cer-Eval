# HAL Vendor Certification Screening - frontend

Next.js (App Router) + TypeScript + Tailwind. Every screen reads and writes the real FastAPI backend; there is no mock data.

```bash
cd frontend
npm install
HAL_BACKEND_URL=http://127.0.0.1:8000 npm run dev      # or: npm run build && npm start
```

`/api/*` is proxied to the backend (`next.config.ts`), so the browser needs no CORS settings and uploaded documents only ever
travel to your own backend.

| Route | Screen |
|---|---|
| `/` | Dashboard (totals, pass/fail/pending, recent evaluations) |
| `/evaluations/new` | Create evaluation (tender upload) |
| `/evaluations/[id]/requirements` | Requirements: review/confirm certification requirements, then technical & commercial criteria and rules |
| `/evaluations/[id]/vendors` | Vendor submissions (multiple vendors, multiple files, ZIP) |
| `/evaluations/[id]/screening` | Workflow progress, start / resume / retry |
| `/evaluations/[id]/certification` | Compliance matrix, evidence, Excel download |
| `/evaluations/[id]/review` | Human review with original document viewer |
| `/evaluations/[id]/technical`, `/commercial` | Only vendors that passed certification |
| `/evaluations/[id]/results` | All vendors, reasons, qualified ranking |

Approvals (confirming requirements, review decisions, resume/retry) need a reviewer token: enter it top right. It is kept in
`sessionStorage` only and sent as `X-Reviewer-Token`. The backend maps tokens to reviewers via `HAL_REVIEWER_TOKENS="alice:token,..."`.
