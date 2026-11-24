"use client";

import { Badge, Card, Empty, ErrorBox, LinkButton, PageHeader, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { downloadUrl } from "@/services/api";
import type { Results, VendorResult } from "@/types/api";

function reason(v: VendorResult): string {
  if (v.eligibility === "FAIL") return `Certification failed: ${v.eligibility_reason}`;
  if (v.eligibility === "PENDING_HUMAN_REVIEW") return `Pending human review: ${v.eligibility_reason}`;
  if (!v.eligibility) return "Not screened yet";
  return v.notes.join("; ") || (v.ranked ? "Qualified" : "");
}

export function ResultsPanel({ evaluationId }: { evaluationId: string }) {
  const { data, error } = useApi<Results>(`/evaluations/${evaluationId}/results`, 5000);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const ranked = data.ranking.map((id) => data.vendors.find((v) => v.vendor_id === id)!).filter(Boolean);
  return (
    <>
      <PageHeader title="Final results" subtitle="All submitted vendors. Vendors that failed or await certification are listed with their reason and are shown as not evaluated, never as scored."
        actions={<LinkButton download href={downloadUrl(`/evaluations/${evaluationId}/reports/consolidated`)}>Download consolidated report</LinkButton>} />
      <div className="space-y-6">
        <Card title="Qualified vendor ranking">
          {ranked.length === 0 ? <Empty>No vendor is fully qualified and commercially valid yet.</Empty> : (
            <ol className="space-y-2">
              {ranked.map((v) => (
                <li key={v.vendor_id} className="flex items-center justify-between rounded-md border border-line p-3">
                  <span className="flex items-center gap-3"><span className="text-lg font-semibold">#{v.rank}</span><span className="font-medium">{v.name}</span></span>
                  <span className="text-sm text-muted">combined {v.combined_score} · technical {v.technical.score}% · price score {v.price_score}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card title="All vendors">
          {data.vendors.length === 0 ? <Empty>No vendors.</Empty> : (
            <Table head={["Rank", "Vendor", "Certification", "Technical", "Commercial", "Price", "Combined", "Reason / note"]}>
              {[...data.vendors].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999) || a.name.localeCompare(b.name)).map((v) => (
                <tr key={v.vendor_id}>
                  <Td>{v.rank ?? "—"}</Td>
                  <Td className="font-medium">{v.name}</Td>
                  <Td><StatusBadge status={v.eligibility} /></Td>
                  <Td><StatusBadge status={v.technical.status} />{v.technical.score != null && <div className="text-xs text-muted">{v.technical.score}%</div>}</Td>
                  <Td><StatusBadge status={v.commercial.status} /></Td>
                  <Td className="whitespace-nowrap">{v.commercial.total_price != null ? `${v.commercial.currency ?? ""} ${v.commercial.total_price.toLocaleString()}` : "—"}</Td>
                  <Td>{v.combined_score ?? "—"}</Td>
                  <Td className="max-w-md text-xs text-muted">{reason(v)}{v.technical.status === "SKIPPED" || v.commercial.status === "SKIPPED" ? <Badge>stage skipped by rule</Badge> : null}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
