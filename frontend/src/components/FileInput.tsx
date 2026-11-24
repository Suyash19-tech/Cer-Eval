"use client";

import { useRef, useState } from "react";

const ALLOWED = [".pdf", ".png", ".jpg", ".jpeg", ".zip"];
const MAX_MB = 50;

/** Client-side pre-check only; the backend re-validates extension, magic bytes, size and ZIP contents. */
export function validateFiles(files: File[], allowed = ALLOWED): string | null {
  for (const f of files) {
    const ext = f.name.toLowerCase().slice(f.name.lastIndexOf("."));
    if (!allowed.includes(ext)) return `${f.name}: unsupported type (allowed: ${allowed.join(", ")})`;
    if (f.size > MAX_MB * 1024 * 1024) return `${f.name}: larger than ${MAX_MB} MB`;
    if (f.size === 0) return `${f.name}: empty file`;
  }
  return null;
}

export function FileInput({ label, multiple, allowed = ALLOWED, onChange }: { label: string; multiple?: boolean; allowed?: string[]; onChange: (f: File[], problem: string | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [names, setNames] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <div>
      <label className="mb-1 block text-sm font-medium">{label}</label>
      <input
        ref={ref}
        type="file"
        multiple={multiple}
        accept={allowed.join(",")}
        className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-brandfg"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          const p = validateFiles(files, allowed);
          setNames(files.map((f) => f.name));
          setProblem(p);
          onChange(files, p);
        }}
      />
      {names.length > 0 && <p className="mt-1 text-xs text-muted">{names.join(", ")}</p>}
      {problem && <p role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">{problem}</p>}
      <p className="mt-1 text-xs text-muted">Allowed: {allowed.join(", ")} · max {MAX_MB} MB each</p>
    </div>
  );
}
