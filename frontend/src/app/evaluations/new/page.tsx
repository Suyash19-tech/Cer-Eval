"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { FileInput } from "@/components/FileInput";
import { Button, Card, ErrorBox, Notice, PageHeader } from "@/components/ui";
import { api } from "@/services/api";
import type { Evaluation } from "@/types/api";

export default function NewEvaluation() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(undefined);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("tender", file);
      const ev = await api.postForm<Evaluation>("/evaluations", form);
      router.push(`/evaluations/${ev.id}/requirements`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Create evaluation" subtitle="Upload the tender PDF. The local Granite model extracts the certification requirements; you review and confirm them before any vendor is screened." />
      <Card className="max-w-2xl">
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="name" className="mb-1 block text-sm font-medium">Evaluation name</label>
            <input id="name" required maxLength={255} value={name} onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm" placeholder="e.g. Hydraulic pump tender 2026" />
          </div>
          <FileInput label="Tender document (PDF)" allowed={[".pdf"]} onChange={(f, p) => { setFile(f[0] ?? null); setProblem(p); }} />
          <Notice>Vendors are added after the requirements are confirmed, on the evaluation&apos;s Vendors tab. Documents stay on this machine; all model inference is local.</Notice>
          {error && <ErrorBox error={error} />}
          <Button disabled={busy || !file || !!problem || !name.trim()}>{busy ? "Uploading…" : "Create and extract requirements"}</Button>
        </form>
      </Card>
    </>
  );
}
