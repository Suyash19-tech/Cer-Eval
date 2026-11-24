"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useReviewerToken } from "@/hooks/useReviewerToken";
import { useApi } from "@/hooks/useApi";

export function AppShell({ children }: { children: ReactNode }) {
  const [token, setToken] = useReviewerToken();
  const health = useApi<{ status: string }>("/health", 30000);
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span className="rounded bg-brand px-2 py-0.5 text-sm text-brandfg">HAL</span>
            Vendor Certification Screening
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <span title="Backend health" className={health.data?.status === "ok" ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}>
              ● {health.data?.status === "ok" ? "backend online" : health.loading ? "connecting…" : "backend offline"}
            </span>
            <label className="flex items-center gap-2">
              <span className="text-muted">Reviewer token</span>
              <input
                type="password"
                value={token}
                autoComplete="off"
                onChange={(e) => setToken(e.target.value)}
                placeholder="needed for approvals"
                className="w-44 rounded-md border border-line bg-bg px-2 py-1"
              />
            </label>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
