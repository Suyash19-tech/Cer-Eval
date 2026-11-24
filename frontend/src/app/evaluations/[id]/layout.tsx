"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import type { Evaluation } from "@/types/api";

const TABS = [
  ["requirements", "1 Requirements"], ["vendors", "2 Vendors"], ["screening", "3 Screening"], ["certification", "4 Certification report"],
  ["review", "5 Human review"], ["technical", "6 Technical"], ["commercial", "7 Commercial"], ["results", "8 Final results"],
] as const;

export default function EvaluationLayout({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const path = usePathname();
  const { data } = useApi<Evaluation>(`/evaluations/${id}`, 5000);
  return (
    <>
      <div className="mb-4">
        <Link href="/" className="text-sm text-muted hover:underline">← Dashboard</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">{data?.name ?? "Evaluation"}</h1>
          {data && <StatusBadge status={data.workflow_status} />}
        </div>
      </div>
      <nav aria-label="Evaluation steps" className="mb-6 flex flex-wrap gap-1 border-b border-line">
        {TABS.map(([slug, label]) => {
          const href = `/evaluations/${id}/${slug}`;
          const active = path === href;
          return (
            <Link key={slug} href={href} aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${active ? "border-brand font-semibold" : "border-transparent text-muted hover:text-fg"}`}>
              {label}
            </Link>
          );
        })}
      </nav>
      {children}
    </>
  );
}
