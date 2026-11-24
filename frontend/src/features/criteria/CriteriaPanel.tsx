"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Notice, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/services/api";
import { AddCriterionForm } from "./AddCriterionForm";
import type { CriteriaState, Criterion, Evaluation } from "@/types/api";

interface Decision { action: "accept" | "reject" | "edit"; reason?: string; edit?: { required_value?: number | null; required_text?: string | null; unit?: string | null; weight?: number; mandatory?: boolean } }
const CMP: Record<string, string> = { GTE: "≥", LTE: "≤", EQ: "=", CONTAINS: "contains" };

export const reqText = (c: Pick<Criterion, "comparator" | "required_value" | "required_text" | "unit">) =>
  `${CMP[c.comparator] ?? c.comparator} ${c.comparator === "CONTAINS" ? `“${c.required_text ?? "?"}”` : c.required_value ?? "?"}${c.unit ? ` ${c.unit}` : ""}`;

export function CriteriaPanel({ evaluationId }: { evaluationId: string }) {
  const ev = useApi<Evaluation>(`/evaluations/${evaluationId}`);
  const { data, error, reload } = useApi<CriteriaState>(`/evaluations/${evaluationId}/criteria`,
    (d) => (d?.criteria_status === "EXTRACTING" ? 2000 : false));
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [cfg, setCfg] = useState({ order: "technical_first", second_stage_requires_first_qualified: true, technical_min_score: 0, weight_technical: 0.5 });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const certConfirmed = ev.data?.requirements_confirmed_at != null;
  const status = data.criteria_status;
  const unresolved = data.criteria.filter((c) => c.needs_human_review && !decisions[c.criterion_code]);
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setProblem(undefined); try { await fn(); await reload(); } catch (e) { setProblem((e as Error).message); } finally { setBusy(false); } };

  return (
    <Card title="Technical & commercial criteria" actions={<StatusBadge status={status} />}>
      <p className="mb-3 text-sm text-muted">Specifications and commercial conditions that vendors are compared against. They are only used for vendors that pass certification, and only after you confirm them.</p>
      {!certConfirmed && <Notice>Confirm the certification requirements first.</Notice>}
      {certConfirmed && ["NOT_STARTED", "FAILED"].includes(status) && (
        <Button disabled={busy} onClick={() => run(() => api.post(`/evaluations/${evaluationId}/criteria/extract`))}>Extract criteria from the tender</Button>
      )}
      {status === "EXTRACTING" && <Spinner label="Granite is extracting criteria…" />}
      {problem && <div className="mt-2"><ErrorBox error={problem} /></div>}
      {data.criteria.length === 0 && status === "PENDING_CONFIRMATION" && <Empty>No technical or commercial criteria were found in the tender.</Empty>}
      {data.criteria.length > 0 && (
        <Table head={["Code", "Kind", "Parameter", "Tender requires", "Page", "Weight", "Decision"]}>
          {data.criteria.map((c) => {
            const d = decisions[c.criterion_code];
            const locked = status === "CONFIRMED";
            return (
              <tr key={c.criterion_code} className={c.rejected ? "opacity-50" : ""}>
                <Td className="font-mono text-xs">{c.criterion_code}</Td>
                <Td><Badge tone={c.kind === "TECHNICAL" ? "blue" : "gray"}>{c.kind}</Badge></Td>
                <Td>
                  <div className="font-medium">{c.name}{!c.mandatory && <span className="ml-1 text-xs text-muted">(optional)</span>}</div>
                  <div className="max-w-md text-xs italic text-muted">“{c.supporting_text}”</div>
                  {c.review_reasons?.map((r) => <div key={r} className="text-xs text-amber-800 dark:text-amber-300">⚠ {r}</div>)}
                </Td>
                <Td className="whitespace-nowrap">{reqText(c)}</Td>
                <Td>{c.source_page ?? "—"}</Td>
                <Td>{c.weight}</Td>
                <Td>
                  {locked ? <StatusBadge status={c.rejected ? "REJECTED" : "CONFIRMED"} /> : (
                    <div className="space-y-1">
                      <select aria-label={`Decision for ${c.criterion_code}`} value={d?.action ?? ""} className="rounded-md border border-line bg-bg px-2 py-1"
                        onChange={(e) => setDecisions((s) => { const n = { ...s }; if (e.target.value) n[c.criterion_code] = { action: e.target.value as Decision["action"], edit: {} }; else delete n[c.criterion_code]; return n; })}>
                        <option value="">{c.needs_human_review ? "Choose…" : "Accept (default)"}</option>
                        <option value="accept">Accept</option><option value="edit">Edit</option><option value="reject">Reject</option>
                      </select>
                      {d?.action === "reject" && <input aria-label="Reason" placeholder="Reason" value={d.reason ?? ""} onChange={(e) => setDecisions((s) => ({ ...s, [c.criterion_code]: { ...d, reason: e.target.value } }))} className="block rounded-md border border-line bg-bg px-2 py-1" />}
                      {d?.action === "edit" && (
                        <div className="flex flex-wrap gap-1">
                          {c.comparator === "CONTAINS"
                            ? <input aria-label="Required wording" placeholder="wording" defaultValue={c.required_text ?? ""} onChange={(e) => setDecisions((s) => ({ ...s, [c.criterion_code]: { ...d, edit: { ...d.edit, required_text: e.target.value } } }))} className="w-32 rounded-md border border-line bg-bg px-2 py-1" />
                            : <input aria-label="Required value" type="number" step="any" placeholder="value" defaultValue={c.required_value ?? ""} onChange={(e) => setDecisions((s) => ({ ...s, [c.criterion_code]: { ...d, edit: { ...d.edit, required_value: e.target.value === "" ? null : Number(e.target.value) } } }))} className="w-24 rounded-md border border-line bg-bg px-2 py-1" />}
                          <input aria-label="Weight" type="number" step="any" min={0} placeholder="weight" defaultValue={c.weight} onChange={(e) => setDecisions((s) => ({ ...s, [c.criterion_code]: { ...d, edit: { ...d.edit, weight: Number(e.target.value) } } }))} className="w-20 rounded-md border border-line bg-bg px-2 py-1" />
                        </div>
                      )}
                    </div>
                  )}
                </Td>
              </tr>
            );
          })}
        </Table>
      )}
      {status === "PENDING_CONFIRMATION" && (
        <div className="mt-4 space-y-3 border-t border-line pt-4">
          <AddCriterionForm evaluationId={evaluationId} onAdded={reload} />
          <h3 className="text-sm font-semibold">Evaluation rules</h3>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label>Stage order{" "}
              <select value={cfg.order} onChange={(e) => setCfg({ ...cfg, order: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1">
                <option value="technical_first">Technical first</option><option value="commercial_first">Commercial first</option><option value="independent">Independent</option>
              </select>
            </label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={cfg.second_stage_requires_first_qualified} onChange={(e) => setCfg({ ...cfg, second_stage_requires_first_qualified: e.target.checked })} /> second stage requires first to qualify</label>
            <label>Min technical score %{" "}<input type="number" min={0} max={100} value={cfg.technical_min_score} onChange={(e) => setCfg({ ...cfg, technical_min_score: Number(e.target.value) })} className="w-20 rounded-md border border-line bg-bg px-2 py-1" /></label>
            <label>Technical weight{" "}<input type="number" min={0} max={1} step={0.05} value={cfg.weight_technical} onChange={(e) => setCfg({ ...cfg, weight_technical: Number(e.target.value) })} className="w-20 rounded-md border border-line bg-bg px-2 py-1" /> (commercial {(1 - cfg.weight_technical).toFixed(2)})</label>
          </div>
          {unresolved.length > 0 && <p className="text-sm text-amber-800 dark:text-amber-300">{unresolved.length} flagged criteria need a decision: {unresolved.map((u) => u.criterion_code).join(", ")}</p>}
          <Button disabled={busy || unresolved.length > 0} onClick={() => run(() => api.post(`/evaluations/${evaluationId}/criteria/confirm`, {
            decisions: Object.entries(decisions).map(([criterion_code, d]) => ({ criterion_code, action: d.action, reason: d.reason, edit: d.action === "edit" ? d.edit : undefined })),
            config: { ...cfg, weight_commercial: Number((1 - cfg.weight_technical).toFixed(4)) },
          }, true))}>Confirm criteria and rules (reviewer token required)</Button>
        </div>
      )}
      {status === "CONFIRMED" && data.config && <p className="mt-3 text-xs text-muted">Rules: {JSON.stringify(data.config)}</p>}
    </Card>
  );
}
