"use client";

import { useState } from "react";
import { Badge, Button, Card, ErrorBox, LinkButton, Notice, PageHeader, Spinner, StatusBadge, Table, Td, formatDate } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, downloadUrl } from "@/services/api";
import type { Evaluation, Vendor, WorkflowState } from "@/types/api";

type StageState = "done" | "active" | "waiting";

export function ScreeningPanel({ evaluationId }: { evaluationId: string }) {
  const ev = useApi<Evaluation>(`/evaluations/${evaluationId}`, 4000);
  const vendors = useApi<Vendor[]>(`/evaluations/${evaluationId}/vendors`, 3000);
  const wf = useApi<WorkflowState>(`/evaluations/${evaluationId}/workflow`, (d) => (d && d.workflow_status === "RUNNING" ? 1500 : 4000));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  if (wf.error) return <ErrorBox error={wf.error} />;
  if (!wf.data || !vendors.data || !ev.data) return <Spinner />;
  const w = wf.data;
  const vs = vendors.data;
  const log = w.node_log;
  const count = (node: string) => log.filter((e) => e.node === node).length;
  const nVendors = vs.length;
  const running = w.workflow_status === "RUNNING";
  const stage = (done: boolean, started: boolean): StageState => (done ? "done" : started && running ? "active" : "waiting");
  const screened = Math.max(count("screen_certificates"), vs.filter((v) => v.screening_status === "DONE").length);
  const stages: [string, StageState, string?][] = [
    ["Tender extraction", ev.data.requirements_confirmed_at ? "done" : "waiting", ev.data.requirements_confirmed_at ? "requirements confirmed" : "confirm requirements first"],
    ["Vendor document processing", nVendors > 0 ? "done" : "waiting", `${vs.reduce((a, v) => a + v.documents.length, 0)} documents from ${nVendors} vendors`],
    ["Document classification", nVendors > 0 ? "done" : "waiting", `${vs.reduce((a, v) => a + v.documents.filter((d) => d.document_class !== "UNKNOWN").length, 0)} classified`],
    ["Certificate extraction", stage(nVendors > 0 && screened >= nVendors, w.started), `${screened}/${nVendors} vendors`],
    ["Certificate validation", stage(nVendors > 0 && screened >= nVendors, w.started), "deterministic checks"],
    ["Compliance report generation", stage(w.certification_reports.length > 0, count("merge_screening") > 0), `${w.certification_reports.length} generated`],
    ["Eligibility gate", stage(vs.length > 0 && vs.every((v) => v.eligibility), w.certification_reports.length > 0), "PASS / FAIL / PENDING"],
  ];

  async function act(path: string, reviewer: boolean) {
    setBusy(true); setProblem(undefined);
    try { await api.post(path, undefined, reviewer); await Promise.all([wf.reload(), vendors.reload(), ev.reload()]); }
    catch (e) { setProblem((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Certification screening" subtitle="The workflow screens every vendor in parallel, builds the compliance report, applies the hard eligibility gate, and only then evaluates PASS vendors."
        actions={<>
          {!w.started && <Button disabled={busy || nVendors === 0 || !ev.data.requirements_confirmed_at} onClick={() => act(`/evaluations/${evaluationId}/workflow/start`, false)}>Start screening workflow</Button>}
          {w.workflow_status === "FAILED" && w.started && !w.awaiting_human_review && w.waiting_for.length > 0 && (
            <Button disabled={busy} onClick={() => act(`/evaluations/${evaluationId}/workflow/retry`, true)}>Retry from checkpoint (reviewer token)</Button>
          )}
          {w.awaiting_human_review && <Button disabled={busy} onClick={() => act(`/evaluations/${evaluationId}/workflow/resume`, true)}>Resume after review (reviewer token)</Button>}
        </>} />
      {problem && <div className="mb-3"><ErrorBox error={problem} /></div>}
      {(ev.data.error || w.errors.length > 0) && <div className="mb-3"><ErrorBox error={[ev.data.error, ...w.errors].filter(Boolean).join(" · ")} /></div>}
      {w.awaiting_human_review && (
        <div className="mb-4"><Notice tone="amber">The workflow is paused: {w.pending_review.map((p) => p.name).join(", ")} need human review. Record decisions on the Human review tab, then resume. Passing vendors have already moved on.</Notice></div>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Progress" className="lg:col-span-1">
          <ol className="space-y-3">
            {stages.map(([label, state, note]) => (
              <li key={label} className="flex items-start gap-3 text-sm">
                <span aria-hidden className={`mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full text-xs ${state === "done" ? "bg-green-600 text-white" : state === "active" ? "animate-pulse bg-blue-600 text-white" : "bg-slate-300 text-slate-700 dark:bg-slate-600 dark:text-slate-200"}`}>{state === "done" ? "✓" : "·"}</span>
                <span><span className="font-medium">{label}</span> <span className="text-muted">— {state}{note ? `, ${note}` : ""}</span></span>
              </li>
            ))}
          </ol>
          {w.certification_reports.length > 0 && <div className="mt-4"><LinkButton download href={downloadUrl(`/evaluations/${evaluationId}/reports/certification`)}>Download certification report (.xlsx)</LinkButton></div>}
        </Card>
        <Card title="Vendors" className="lg:col-span-2">
          <Table head={["Vendor", "Screening", "Eligibility", "Reason", "Downstream"]}>
            {vs.map((v) => {
              const r = w.vendor_results[v.id];
              const entered = r?.technical || r?.commercial;
              return (
                <tr key={v.id}>
                  <Td className="font-medium">{v.name}</Td>
                  <Td><StatusBadge status={v.screening_status} /></Td>
                  <Td><StatusBadge status={v.eligibility} /></Td>
                  <Td className="max-w-sm text-xs text-muted">{v.eligibility_reason ?? v.screening_error ?? "—"}</Td>
                  <Td>{v.eligibility === "PASS" ? (entered ? <Badge tone="green">evaluated</Badge> : <Badge>queued</Badge>)
                    : v.eligibility ? <Badge tone={v.eligibility === "FAIL" ? "red" : "amber"}>{v.eligibility === "FAIL" ? "stopped" : "waiting"}</Badge> : "—"}</Td>
                </tr>
              );
            })}
          </Table>
        </Card>
      </div>
      <details className="mt-6">
        <summary className="cursor-pointer text-sm font-medium">Workflow log ({log.length})</summary>
        <div className="mt-2"><Card><Table head={["Time", "Node", "Status", "Detail"]}>
          {log.map((e, i) => (
            <tr key={i}><Td className="text-muted">{formatDate(e.ts)}</Td><Td className="font-mono text-xs">{e.node}</Td><Td>{e.status}</Td>
              <Td className="text-xs text-muted">{Object.entries(e).filter(([k]) => !["node", "status", "ts"].includes(k)).map(([k, x]) => `${k}=${String(x)}`).join(" ")}</Td></tr>
          ))}
        </Table></Card></div>
      </details>
    </>
  );
}
