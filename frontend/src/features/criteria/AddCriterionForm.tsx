"use client";

import { useState } from "react";
import { Button, ErrorBox } from "@/components/ui";
import { api } from "@/services/api";

const PARAMS = ["delivery_days", "payment_days", "validity_days", "total_price", "unit_price", "quantity"];
const input = "rounded-md border border-line bg-bg px-2 py-1";
const blank = { kind: "TECHNICAL", name: "", parameter: "", comparator: "GTE", value: "", text: "", unit: "", mandatory: true, weight: "1", quote: "", reason: "" };

/** Lets a reviewer add a criterion that extraction missed. The quote must exist verbatim in the tender (checked server-side). */
export function AddCriterionForm({ evaluationId, onAdded }: { evaluationId: string; onAdded: () => Promise<unknown> | void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const set = (patch: Partial<typeof blank>) => setF((s) => ({ ...s, ...patch }));
  const contains = f.comparator === "CONTAINS";

  if (!open) return <Button variant="secondary" onClick={() => setOpen(true)}>Add a missed criterion</Button>;

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await api.post(`/evaluations/${evaluationId}/criteria`, {
        kind: f.kind, name: f.name, parameter: f.kind === "COMMERCIAL" && f.parameter ? f.parameter : null, comparator: f.comparator,
        required_value: contains || f.value === "" ? null : Number(f.value), required_text: contains ? f.text : null,
        unit: f.unit || null, mandatory: f.mandatory, weight: Number(f.weight), supporting_text: f.quote, reason: f.reason,
      }, true);
      setF(blank);
      setOpen(false);
      await onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-line p-3 text-sm">
      <h3 className="font-semibold">Add a criterion extraction missed</h3>
      <div className="flex flex-wrap items-end gap-2">
        <label>Kind<select value={f.kind} onChange={(e) => set({ kind: e.target.value })} className={`ml-1 ${input}`}><option>TECHNICAL</option><option>COMMERCIAL</option></select></label>
        <label>Name<input value={f.name} onChange={(e) => set({ name: e.target.value })} className={`ml-1 w-48 ${input}`} /></label>
        {f.kind === "COMMERCIAL" && (
          <label>Parameter<select value={f.parameter} onChange={(e) => set({ parameter: e.target.value })} className={`ml-1 ${input}`}><option value="">none</option>{PARAMS.map((p) => <option key={p}>{p}</option>)}</select></label>
        )}
        <label>Comparator<select value={f.comparator} onChange={(e) => set({ comparator: e.target.value })} className={`ml-1 ${input}`}><option value="GTE">≥</option><option value="LTE">≤</option><option value="EQ">=</option><option value="CONTAINS">contains</option></select></label>
        {contains
          ? <label>Wording<input value={f.text} onChange={(e) => set({ text: e.target.value })} className={`ml-1 w-40 ${input}`} /></label>
          : <label>Value<input type="number" step="any" value={f.value} onChange={(e) => set({ value: e.target.value })} className={`ml-1 w-24 ${input}`} /></label>}
        <label>Unit<input value={f.unit} onChange={(e) => set({ unit: e.target.value })} className={`ml-1 w-20 ${input}`} /></label>
        <label>Weight<input type="number" min={0} step="any" value={f.weight} onChange={(e) => set({ weight: e.target.value })} className={`ml-1 w-20 ${input}`} /></label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={f.mandatory} onChange={(e) => set({ mandatory: e.target.checked })} /> mandatory</label>
      </div>
      <label className="block">Exact sentence from the tender
        <textarea value={f.quote} onChange={(e) => set({ quote: e.target.value })} rows={2} className={`mt-1 block w-full ${input}`} />
      </label>
      <label className="block">Why was it missed? (audited)
        <input value={f.reason} onChange={(e) => set({ reason: e.target.value })} className={`mt-1 block w-full ${input}`} />
      </label>
      {error && <ErrorBox error={error} />}
      <div className="flex gap-2">
        <Button disabled={busy || !f.name || f.quote.length < 8 || f.reason.length < 10} onClick={submit}>Add criterion (reviewer token required)</Button>
        <Button variant="secondary" onClick={() => { setOpen(false); setError(undefined); }}>Cancel</Button>
      </div>
    </div>
  );
}
