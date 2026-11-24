"use client";

import { useState } from "react";
import { FileInput } from "@/components/FileInput";
import { Badge, Button, Card, Empty, ErrorBox, Notice, PageHeader, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/services/api";
import type { Evaluation, Vendor } from "@/types/api";

export function VendorsPanel({ evaluationId }: { evaluationId: string }) {
  const ev = useApi<Evaluation>(`/evaluations/${evaluationId}`);
  const { data: vendors, error, reload } = useApi<Vendor[]>(`/evaluations/${evaluationId}/vendors`, 5000);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [formKey, setFormKey] = useState(0);
  const confirmed = ev.data?.requirements_confirmed_at != null;

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(undefined);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      files.forEach((f) => form.append("files", f));
      await api.postForm(`/evaluations/${evaluationId}/vendors`, form);
      setName(""); setFiles([]); setFormKey((k) => k + 1);
      await reload();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Vendor submissions" subtitle="Each document belongs to exactly one vendor and is indexed in that vendor's own isolated index." />
      {!confirmed && <div className="mb-4"><Notice tone="amber">Vendors can be added once the certification requirements are confirmed.</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Add a vendor" className="lg:col-span-1">
          <form onSubmit={add} className="space-y-3" key={formKey}>
            <div>
              <label htmlFor="vname" className="mb-1 block text-sm font-medium">Vendor name</label>
              <input id="vname" required value={name} maxLength={255} onChange={(e) => setName(e.target.value)} className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm" />
            </div>
            <FileInput label="Documents (certificates, quotations, ZIP)" multiple onChange={(f, p) => { setFiles(f); setProblem(p); }} />
            {err && <ErrorBox error={err} />}
            <Button disabled={!confirmed || busy || !name.trim() || files.length === 0 || !!problem}>{busy ? "Processing documents…" : "Upload vendor"}</Button>
          </form>
        </Card>
        <Card title={`Vendors (${vendors?.length ?? 0})`} className="lg:col-span-2">
          {error && <ErrorBox error={error} />}
          {!vendors ? <Spinner /> : vendors.length === 0 ? <Empty>No vendors yet.</Empty> : (
            <Table head={["Vendor", "Documents", "Screening", "Eligibility"]}>
              {vendors.map((v) => (
                <tr key={v.id}>
                  <Td className="font-medium">{v.name}</Td>
                  <Td>
                    <ul className="space-y-1">
                      {v.documents.map((d) => (
                        <li key={d.id} className="text-xs">
                          {d.filename} <Badge>{d.document_class.replaceAll("_", " ")}</Badge>{d.page_count != null && <span className="text-muted"> {d.page_count}p</span>}
                          {d.needs_flag && <span className="ml-1 text-amber-800 dark:text-amber-300">⚠ {d.needs_flag}</span>}
                        </li>
                      ))}
                    </ul>
                  </Td>
                  <Td><StatusBadge status={v.screening_status} /></Td>
                  <Td><StatusBadge status={v.eligibility} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
