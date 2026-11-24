"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Notice, Spinner, StatusBadge, formatDate } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/services/api";
import type { Evaluation, Requirement } from "@/types/api";

type Action = "accept" | "reject" | "edit";
interface Decision { action: Action; reason?: string; edits?: { certificate_name?: string | null; standard?: string | null; version?: string | null; mandatory?: boolean } }

const CAT_LABEL: Record<string, string> = { X: "Category X", Y: "Category Y", Z: "Category Z", OTHER_CERTIFICATION: "Other certifications", ELIGIBILITY_CONDITION: "Eligibility conditions" };

export function RequirementsPanel({ evaluationId }: { evaluationId: string }) {
  const { data: ev, error, reload } = useApi<Evaluation>(`/evaluations/${evaluationId}`,
    (d) => (d && ["EXTRACTING_REQUIREMENTS", "CREATED"].includes(d.workflow_status) ? 2000 : false));
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [extra, setExtra] = useState({ category: "OTHER_CERTIFICATION", description: "", standard: "", version: "", supporting_text: "" });
  const [additions, setAdditions] = useState<typeof extra[]>([]);

  if (error) return <ErrorBox error={error} />;
  if (!ev) return <Spinner />;
  const confirmed = ev.requirements_confirmed_at !== null;
  const extracting = ev.workflow_status === "EXTRACTING_REQUIREMENTS" || ev.workflow_status === "CREATED";
  const reqs = ev.requirements;
  const unresolved = reqs.filter((r) => r.needs_human_review && !decisions[r.requirement_code]);
  const groups = Object.keys(CAT_LABEL).map((c) => [c, reqs.filter((r) => r.category === c)] as const).filter(([, l]) => l.length);

  const setD = (code: string, d: Decision | undefined) => setDecisions((s) => { const n = { ...s }; if (d) n[code] = d; else delete n[code]; return n; });

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      const body = {
        decisions: Object.entries(decisions).map(([requirement_id, d]) => ({ requirement_id, action: d.action, reason: d.reason, edits: d.edits })),
        additions: additions.map((a) => ({ category: a.category, description: a.description, mandatory: true, standard: a.standard || null, version: a.version || null, supporting_text: a.supporting_text })),
      };
      await api.post(`/evaluations/${evaluationId}/requirements/confirm`, body, true);
      await reload();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Certification requirements" actions={confirmed
      ? <Badge tone="green">Confirmed by {ev.requirements_confirmed_by} · {formatDate(ev.requirements_confirmed_at)}</Badge>
      : <StatusBadge status={ev.workflow_status} />}>
      {extracting && <Spinner label="Granite is extracting requirements from the tender (local inference, can take a minute)…" />}
      {ev.workflow_status === "FAILED" && <ErrorBox error={ev.error ?? "Extraction failed"} />}
      {!extracting && reqs.length === 0 && ev.workflow_status !== "FAILED" && <Empty>No requirements were extracted. Add them manually below (each must quote the tender).</Empty>}
      {!confirmed && reqs.length > 0 && (
        <Notice tone="amber">Nothing is confirmed automatically. Review every requirement against the quoted tender text. Items flagged for review need an explicit decision.</Notice>
      )}
      <div className="mt-4 space-y-6">
        {groups.map(([cat, list]) => (
          <div key={cat}>
            <h3 className="mb-2 text-sm font-semibold">{CAT_LABEL[cat]}</h3>
            <ul className="space-y-3">
              {list.map((r) => (
                <RequirementRow key={r.requirement_code} r={r} locked={confirmed} decision={decisions[r.requirement_code]} onChange={(d) => setD(r.requirement_code, d)} />
              ))}
            </ul>
          </div>
        ))}
      </div>

      {!confirmed && !extracting && (
        <div className="mt-6 space-y-4 border-t border-line pt-4">
          <details>
            <summary className="cursor-pointer text-sm font-medium">Add a requirement the extractor missed</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <select value={extra.category} onChange={(e) => setExtra({ ...extra, category: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1.5 text-sm">
                {["X", "Y", "Z", "OTHER_CERTIFICATION"].map((c) => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
              </select>
              <input placeholder="Description" value={extra.description} onChange={(e) => setExtra({ ...extra, description: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1.5 text-sm" />
              <input placeholder="Standard (e.g. ISO 9001)" value={extra.standard} onChange={(e) => setExtra({ ...extra, standard: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1.5 text-sm" />
              <input placeholder="Version / year" value={extra.version} onChange={(e) => setExtra({ ...extra, version: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1.5 text-sm" />
              <textarea placeholder="Exact tender text that states it (must exist in the tender)" value={extra.supporting_text} onChange={(e) => setExtra({ ...extra, supporting_text: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1.5 text-sm md:col-span-2" rows={2} />
              <Button variant="secondary" disabled={!extra.description || extra.supporting_text.length < 10}
                onClick={() => { setAdditions([...additions, extra]); setExtra({ ...extra, description: "", standard: "", version: "", supporting_text: "" }); }}>Queue addition</Button>
            </div>
            {additions.length > 0 && <p className="mt-2 text-xs text-muted">{additions.length} addition(s) queued, sent on confirm.</p>}
          </details>
          {problem && <ErrorBox error={problem} />}
          {unresolved.length > 0 && <p className="text-sm text-amber-800 dark:text-amber-300">{unresolved.length} flagged requirement(s) still need a decision: {unresolved.map((u) => u.requirement_code).join(", ")}</p>}
          <Button onClick={confirm} disabled={busy || extracting || unresolved.length > 0 || (reqs.length === 0 && additions.length === 0)}>
            {busy ? "Confirming…" : "Confirm requirements (reviewer token required)"}
          </Button>
        </div>
      )}
    </Card>
  );
}

function RequirementRow({ r, locked, decision, onChange }: { r: Requirement; locked: boolean; decision?: Decision; onChange: (d?: Decision) => void }) {
  const conds = r.validation_conditions?.conditions ?? [];
  return (
    <li className={`rounded-md border p-3 ${r.rejected ? "opacity-60" : ""} ${r.needs_human_review ? "border-amber-400" : "border-line"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted">{r.requirement_code}</span>
        <Badge tone={r.mandatory ? "blue" : "gray"}>{r.mandatory ? "Mandatory" : "Optional"}</Badge>
        {r.standard && <Badge>{r.standard}{r.version ? ` · ${r.version}` : ""}</Badge>}
        <Badge>{r.source_page ? `Tender page ${r.source_page}` : "page not located"}</Badge>
        {r.rejected && <Badge tone="red">Rejected</Badge>}
        {r.confirmed && <Badge tone="green">Confirmed</Badge>}
        {r.needs_human_review && !locked && <Badge tone="amber">Needs your decision</Badge>}
      </div>
      <p className="mt-2 text-sm font-medium">{r.description}</p>
      <blockquote className="mt-1 border-l-2 border-line pl-3 text-sm italic text-muted">“{r.supporting_text}”</blockquote>
      {conds.length > 0 && <p className="mt-1 text-xs text-muted">Conditions: {conds.join("; ")}</p>}
      {r.review_reasons && r.review_reasons.length > 0 && (
        <ul className="mt-2 list-inside list-disc text-xs text-amber-800 dark:text-amber-300">{r.review_reasons.map((x) => <li key={x}>{x}</li>)}</ul>
      )}
      {!locked && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <select aria-label={`Decision for ${r.requirement_code}`} value={decision?.action ?? ""} className="rounded-md border border-line bg-bg px-2 py-1"
            onChange={(e) => onChange(e.target.value ? { action: e.target.value as Action, edits: e.target.value === "edit" ? {} : undefined } : undefined)}>
            <option value="">{r.needs_human_review ? "Choose…" : "Accept (default)"}</option>
            <option value="accept">Accept as extracted</option>
            <option value="edit">Edit then accept</option>
            <option value="reject">Reject</option>
          </select>
          {decision?.action === "reject" && (
            <input aria-label="Reason" placeholder="Reason (required)" value={decision.reason ?? ""} onChange={(e) => onChange({ ...decision, reason: e.target.value })} className="min-w-64 rounded-md border border-line bg-bg px-2 py-1" />
          )}
          {decision?.action === "edit" && (
            <>
              <input aria-label="Certificate name" placeholder="Certificate name" defaultValue={r.certificate_name ?? ""} onChange={(e) => onChange({ ...decision, edits: { ...decision.edits, certificate_name: e.target.value || null } })} className="rounded-md border border-line bg-bg px-2 py-1" />
              <input aria-label="Standard" placeholder="Standard" defaultValue={r.standard ?? ""} onChange={(e) => onChange({ ...decision, edits: { ...decision.edits, standard: e.target.value || null } })} className="w-32 rounded-md border border-line bg-bg px-2 py-1" />
              <input aria-label="Version" placeholder="Version" defaultValue={r.version ?? ""} onChange={(e) => onChange({ ...decision, edits: { ...decision.edits, version: e.target.value || null } })} className="w-24 rounded-md border border-line bg-bg px-2 py-1" />
              <label className="flex items-center gap-1"><input type="checkbox" defaultChecked={r.mandatory} onChange={(e) => onChange({ ...decision, edits: { ...decision.edits, mandatory: e.target.checked } })} /> mandatory</label>
            </>
          )}
        </div>
      )}
    </li>
  );
}
