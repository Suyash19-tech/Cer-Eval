/* eslint-disable @next/next/no-img-element -- originals are served by our own backend, not optimisable remote images */
"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Notice, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, downloadUrl } from "@/services/api";
import type { EvaluationDetails, Vendor } from "@/types/api";

interface Item {
  key: string;
  type: "CERT" | "CRITERION" | "COMMERCIAL";
  vendor: Vendor;
  code: string;
  title: string;
  status: string;
  reasons: string[];
  quote?: string;
  documentId?: string;
  page?: number;
  fields: [string, unknown][];
  decisions: string[];
}

export function ReviewPanel({ evaluationId }: { evaluationId: string }) {
  const vendors = useApi<Vendor[]>(`/evaluations/${evaluationId}/vendors`, 5000);
  const details = useApi<EvaluationDetails>(`/evaluations/${evaluationId}/evaluation-details`, 5000);
  const [selKey, setSelKey] = useState<string>();
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [done, setDone] = useState<string>();

  if (vendors.error) return <ErrorBox error={vendors.error} />;
  if (!vendors.data || !details.data) return <Spinner />;

  const items: Item[] = [];
  for (const v of vendors.data) {
    for (const f of v.findings.filter((x) => x.status === "NEEDS_HUMAN_REVIEW")) {
      const e = f.evidence ?? {};
      items.push({ key: `c:${v.id}:${f.requirement_code}`, type: "CERT", vendor: v, code: f.requirement_code, title: `Certificate ${f.requirement_code}`,
        status: f.status, reasons: f.reasons ?? [], quote: e.supporting_text, documentId: e.document_id, page: e.page_number,
        fields: [["Holder", e.holder_name], ["Certificate no.", e.certificate_number], ["Issuer", e.issuer], ["Expiry text", e.expiry_text], ["Parsed expiry", e.expiry_date], ["Version found", e.version_found], ["Document", e.document_name], ["Page", e.page_number]],
        decisions: ["COMPLIANT", "MISSING", "EXPIRED", "MISMATCH"] });
    }
  }
  for (const f of details.data.findings.filter((x) => ["NEEDS_HUMAN_REVIEW", "MISSING_DETAIL"].includes(x.status))) {
    const v = vendors.data.find((x) => x.id === f.vendor_id)!;
    items.push({ key: `k:${f.vendor_id}:${f.criterion_code}`, type: "CRITERION", vendor: v, code: f.criterion_code, title: `${f.kind === "TECHNICAL" ? "Technical" : "Commercial"} ${f.criterion_code}: ${f.name}`,
      status: f.status, reasons: f.reasons, quote: f.evidence.supporting_text, documentId: f.evidence.document_id, page: f.evidence.page_number,
      fields: [["Tender requires", `${f.comparator ?? ""} ${f.required_value ?? f.required_text ?? ""} ${f.unit ?? ""}`], ["Tender page", f.tender_page], ["Vendor value", f.evidence.vendor_value], ["Document", f.evidence.document_name]],
      decisions: ["MEETS", "DEVIATES"] });
  }
  for (const s of details.data.commercial.filter((x) => x.needs_human_review)) {
    const v = vendors.data.find((x) => x.id === s.vendor_id)!;
    items.push({ key: `m:${s.vendor_id}`, type: "COMMERCIAL", vendor: v, code: "COMMERCIAL_SUMMARY", title: "Commercial summary",
      status: "NEEDS_HUMAN_REVIEW", reasons: s.review_reasons, quote: Object.values((s.data.quotes ?? {}) as Record<string, string>).join("\n"),
      fields: Object.entries(s.data).filter(([k]) => k !== "quotes"), decisions: ["APPROVE"] });
  }
  const sel = items.find((i) => i.key === selKey) ?? items[0];

  async function submit() {
    if (!sel) return;
    setBusy(true); setProblem(undefined); setDone(undefined);
    try {
      const base = `/evaluations/${evaluationId}/vendors/${sel.vendor.id}`;
      if (sel.type === "CERT") await api.post(`${base}/review`, { requirement_code: sel.code, decision, reason }, true);
      else if (sel.type === "CRITERION") await api.post(`${base}/criteria/review`, { criterion_code: sel.code, decision, reason }, true);
      else await api.post(`${base}/commercial/approve`, { reason }, true);
      setDone(`Recorded: ${sel.vendor.name} · ${sel.code} → ${decision}. If the vendor now passes, resume the workflow on the Screening tab.`);
      setDecision(""); setReason(""); setSelKey(undefined);
      await Promise.all([vendors.reload(), details.reload()]);
    } catch (e) { setProblem((e as Error).message); } finally { setBusy(false); }
  }

  const doc = sel?.documentId ? sel.vendor.documents.find((d) => d.id === sel.documentId) : undefined;
  const url = sel?.documentId ? downloadUrl(`/evaluations/${evaluationId}/vendors/${sel.vendor.id}/documents/${sel.documentId}/file`) : undefined;
  const isImage = doc && /\.(png|jpe?g)$/i.test(doc.filename);

  return (
    <>
      <PageHeader title="Human review" subtitle="The model's output is shown for inspection only. It never approves its own uncertain extraction: an authorised reviewer decides, with a recorded reason." />
      {done && <div className="mb-3"><Notice>{done}</Notice></div>}
      {items.length === 0 ? <Empty>Nothing is waiting for review.</Empty> : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title={`Pending (${items.length})`} className="lg:col-span-1">
            <ul className="space-y-2">
              {items.map((i) => (
                <li key={i.key}>
                  <button onClick={() => { setSelKey(i.key); setDecision(""); setReason(""); setProblem(undefined); }} aria-current={sel?.key === i.key}
                    className={`w-full rounded-md border p-2 text-left text-sm ${sel?.key === i.key ? "border-brand bg-bg" : "border-line"}`}>
                    <div className="font-medium">{i.vendor.name}</div>
                    <div className="text-xs text-muted">{i.title}</div>
                    <div className="mt-1"><StatusBadge status={i.status} /></div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {sel && (
            <div className="space-y-4 lg:col-span-2">
              <Card title={`${sel.vendor.name} — ${sel.title}`} actions={<Badge tone="amber">{sel.type.toLowerCase()}</Badge>}>
                <h3 className="text-sm font-semibold">Why it needs a human</h3>
                <ul className="mb-3 list-inside list-disc text-sm">{sel.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                {sel.quote && <><h3 className="text-sm font-semibold">Quoted evidence (proposed by the model, verified to exist in the document)</h3>
                  <blockquote className="mb-3 whitespace-pre-line border-l-2 border-line pl-3 text-sm italic text-muted">“{sel.quote}”</blockquote></>}
                <h3 className="text-sm font-semibold">Extracted fields</h3>
                <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm md:grid-cols-3">
                  {sel.fields.map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd>{v == null || v === "" ? "—" : String(v)}</dd></div>)}
                </dl>
                <div className="rounded-md border border-line p-3">
                  <label className="mb-1 block text-sm font-medium">Your decision</label>
                  <div className="flex flex-wrap gap-3 text-sm">
                    {sel.decisions.map((d) => <label key={d} className="flex items-center gap-1"><input type="radio" name="decision" checked={decision === d} onChange={() => setDecision(d)} />{d}</label>)}
                  </div>
                  <label htmlFor="reason" className="mb-1 mt-3 block text-sm font-medium">Reason (min 10 characters, recorded in the audit log)</label>
                  <textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm" />
                  {problem && <div className="mt-2"><ErrorBox error={problem} /></div>}
                  <div className="mt-3"><Button disabled={busy || !decision || reason.trim().length < 10} onClick={submit}>{busy ? "Submitting…" : "Submit decision (reviewer token required)"}</Button></div>
                </div>
              </Card>
              {url && (
                <Card title={`Original document: ${doc?.filename ?? ""}`} actions={<a className="text-sm underline" href={url} target="_blank" rel="noreferrer">open in new tab</a>}>
                  {isImage ? <img src={url} alt={`Original ${doc?.filename}`} className="max-h-[600px] w-full object-contain" />
                    : <iframe title="Original document" src={`${url}#page=${sel.page ?? 1}`} className="h-[600px] w-full rounded-md border border-line" />}
                </Card>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
