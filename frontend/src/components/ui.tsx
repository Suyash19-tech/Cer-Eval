"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ApiError } from "@/services/api";

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-surface shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

type Variant = "primary" | "secondary" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-brandfg hover:opacity-90",
  secondary: "border border-line bg-surface hover:bg-bg",
  danger: "bg-red-700 text-white hover:bg-red-800",
};

export function Button({ variant = "primary", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button {...rest} className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`} />;
}

export function LinkButton({ href, children, variant = "secondary", download }: { href: string; children: ReactNode; variant?: Variant; download?: boolean }) {
  const cls = `inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium ${VARIANTS[variant]}`;
  return download ? <a href={href} className={cls}>{children}</a> : <Link href={href} className={cls}>{children}</Link>;
}

const TONES: Record<string, string> = {
  green: "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-200",
  red: "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200",
  amber: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  blue: "bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-200",
  gray: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
};

const STATUS_TONE: Record<string, string> = {
  PASS: "green", COMPLIANT: "green", MEETS: "green", QUALIFIED: "green", VALID: "green", COMPLETED: "green", DONE: "green", CONFIRMED: "green",
  FAIL: "red", MISSING: "red", EXPIRED: "red", MISMATCH: "red", DEVIATES: "red", NOT_QUALIFIED: "red", FAILED: "red",
  PENDING_HUMAN_REVIEW: "amber", NEEDS_HUMAN_REVIEW: "amber", NEEDS_REVIEW: "amber", MISSING_DETAIL: "amber",
  AWAITING_HUMAN_REVIEW: "amber", REQUIREMENTS_PENDING_CONFIRMATION: "amber", PENDING_CONFIRMATION: "amber",
  RUNNING: "blue", SCREENING: "blue", EXTRACTING: "blue", EXTRACTING_REQUIREMENTS: "blue",
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "NOT_SCREENED";
  return <Badge tone={STATUS_TONE[s] ?? "gray"}>{s.replaceAll("_", " ")}</Badge>;
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <p role="status" className="py-6 text-sm text-muted">{label}</p>;
}

export function ErrorBox({ error }: { error: ApiError | Error | string }) {
  const msg = typeof error === "string" ? error : error.message;
  return <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">{msg}</div>;
}

export function Notice({ tone = "blue", children }: { tone?: "blue" | "amber"; children: ReactNode }) {
  const cls = tone === "amber" ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
    : "border-blue-300 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200";
  return <div className={`rounded-md border p-3 text-sm ${cls}`}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-dashed border-line p-6 text-center text-sm text-muted">{children}</p>;
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
            {head.map((h, i) => <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export const Td = ({ children, className = "" }: { children?: ReactNode; className?: string }) => <td className={`px-3 py-2 align-top ${className}`}>{children}</td>;

export function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}
