"use client";

import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, LinkButton, Notice, PageHeader, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { downloadUrl } from "@/services/api";
import type { Evaluation, Finding, Vendor } from "@/types/api";

const FILTERS = [["ALL", "All"], ["X", "X"], ["Y", "Y"], ["Z", "Z"], ["OTHER_CERTIFICATION", "Other"], ["EXCEPTIONS", "Exceptions only"]] as const;

export function CertificationMatrix({ evaluationId }: { evaluationId: string }) {
  const ev = useApi<Evaluation>(`/evaluations/${evaluationId}`);
  const vendors = useApi<Vendor[]>(`/evaluations/${evaluationId}/vendors`, 5000);
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("ALL");
  const [sel, setSel] = useState<{ vendor: Vendor; finding: Finding; req: string } | null>(null);

  if (ev.error) return <ErrorBox error={ev.error} />;
  if (!ev.data || !vendors.data) return <Spinner />;
  const reqs = ev.data.requirements.filter((r) => r.confirmed && !r.rejected && r.category !== "ELIGIBILITY_CONDITION");
  const shown = reqs.filter((r) => filter === "ALL" || (filter === "EXCEPTIONS" ? vendors.data!.some((v) => { const f = v.findings.find((x) => x.requirement_code === r.requirement_code); return f && f.status !== "COMPLIANT"; }) : r.category === filter));
  const vs = vendors.data;
  const count = (st: string) => vs.reduce((a, v) => a + v.findings.filter((f) => f.status === st).length, 0);

  return (
    <>
      <PageHeader title="Certification compliance report" subtitle="Statuses are decided by deterministic validation of quoted evidence. The model never declares a certificate compliant."
        actions={<LinkButton download href={downloadUrl(`/evaluations/${evaluationId}/reports/certification`)}>Download Excel report</LinkButton>} />
      {reqs.length === 0 || vs.length === 0 ? <Empty>Confirm requirements and add vendors, then run the screening workflow.</Empty> : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            {FILTERS.map(([k, l]) => <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k} className={`rounded-full border px-3 py-1 ${filter === k ? "border-brand bg-brand text-brandfg" : "border-line bg-surface"}`}>{l}</button>)}
            <span className="ml-auto text-muted">Missing {count("MISSING")} · Expired {count("EXPIRED")} · Mismatch {count("MISMATCH")} · Review {count("NEEDS_HUMAN_REVIEW")}</span>
          </div>
          <Card title="Vendor-wise compliance matrix">
            <Table head={["Requirement", ...vs.map((v) => v.name)]}>
              {shown.map((r) => (
                <tr key={r.requirement_code}>
                  <Td>
                    <div className="font-mono text-xs text-muted">{r.requirement_code} · {r.category.replace("_CERTIFICATION", "")}</div>
                    <div className="font-medium">{r.certificate_name ?? r.standard ?? r.description}</div>
                    <div className="text-xs text-muted">{r.mandatory ? "Mandatory" : "Optional"}{r.source_page ? ` · tender p.${r.source_page}` : ""}</div>
                  </Td>
                  {vs.map((v) => {
                    const f = v.findings.find((x) => x.requirement_code === r.requirement_code);
                    return (
                      <Td key={v.id}>
                        {f ? <button onClick={() => setSel({ vendor: v, finding: f, req: r.requirement_code })} className="text-left" aria-label={`${v.name} ${r.requirement_code} ${f.status}`}><StatusBadge status={f.status} />{f.evidence?.expiry_date && <div className="mt-1 text-xs text-muted">exp {f.evidence.expiry_date}</div>}</button>
                          : <span className="text-xs text-muted">not screened</span>}
                      </Td>
                    );
                  })}
                </tr>
              ))}
              <tr className="bg-bg font-semibold">
                <Td>Final eligibility</Td>
                {vs.map((v) => <Td key={v.id}><StatusBadge status={v.eligibility} /></Td>)}
              </tr>
            </Table>
          </Card>
          {vs.some((v) => v.eligibility === "FAIL" || v.eligibility === "PENDING_HUMAN_REVIEW") && (
            <div className="mt-4 space-y-2">
              {vs.filter((v) => v.eligibility === "FAIL" || v.eligibility === "PENDING_HUMAN_REVIEW").map((v) => (
                <Notice key={v.id} tone={v.eligibility === "FAIL" ? "blue" : "amber"}><strong>{v.name}</strong> — {v.eligibility_reason}</Notice>
              ))}
            </div>
          )}
          {sel && (
            <Card title={`Evidence: ${sel.vendor.name} · ${sel.req}`} className="mt-4" actions={<button onClick={() => setSel(null)} className="text-sm underline">close</button>}>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2"><StatusBadge status={sel.finding.status} />{sel.finding.resolved_by && <Badge tone="blue">resolved by {sel.finding.resolved_by}</Badge>}</div>
                <ul className="list-inside list-disc">{(sel.finding.reasons ?? []).map((x) => <li key={x}>{x}</li>)}</ul>
                {sel.finding.evidence?.supporting_text && (
                  <>
                    <blockquote className="border-l-2 border-line pl-3 italic text-muted">“{sel.finding.evidence.supporting_text}”</blockquote>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-4">
                      {([["Source document", sel.finding.evidence.document_name], ["Page", sel.finding.evidence.page_number], ["Holder", sel.finding.evidence.holder_name], ["Certificate no.", sel.finding.evidence.certificate_number], ["Issuer", sel.finding.evidence.issuer], ["Expiry", sel.finding.evidence.expiry_date ?? sel.finding.evidence.expiry_text], ["Version found", sel.finding.evidence.version_found]] as const).map(([k, val]) => (
                        <div key={k}><dt className="text-muted">{k}</dt><dd>{val ?? "—"}</dd></div>
                      ))}
                    </dl>
                    {sel.finding.evidence.document_id && <a className="text-sm underline" target="_blank" rel="noreferrer" href={downloadUrl(`/evaluations/${evaluationId}/vendors/${sel.vendor.id}/documents/${sel.finding.evidence.document_id}/file#page=${sel.finding.evidence.page_number ?? 1}`)}>Open original document</a>}
                  </>
                )}
              </div>
            </Card>
          )}
        </>
      )}
    </>
  );
}
