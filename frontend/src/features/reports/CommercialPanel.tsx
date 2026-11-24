"use client";

import { Card, Empty, ErrorBox, LinkButton, Notice, PageHeader, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { reqText } from "@/features/criteria/CriteriaPanel";
import { useApi } from "@/hooks/useApi";
import { downloadUrl } from "@/services/api";
import type { EvaluationDetails, Results } from "@/types/api";

const money = (v: unknown, cur: unknown) => (typeof v === "number" ? `${cur ?? ""} ${v.toLocaleString()}`.trim() : "not stated");
const num = (v: unknown, unit = "") => (typeof v === "number" ? `${v}${unit}` : "not stated");

export function CommercialPanel({ evaluationId }: { evaluationId: string }) {
  const results = useApi<Results>(`/evaluations/${evaluationId}/results`, 5000);
  const details = useApi<EvaluationDetails>(`/evaluations/${evaluationId}/evaluation-details`, 5000);
  if (results.error) return <ErrorBox error={results.error} />;
  if (!results.data || !details.data) return <Spinner />;
  const qualified = results.data.vendors.filter((v) => v.eligibility === "PASS");
  const excluded = results.data.vendors.length - qualified.length;
  return (
    <>
      <PageHeader title="Commercial evaluation" subtitle="Only certification-qualified vendors appear here. Terms are quoted from the vendor's commercial quotation; anything not stated stays “not stated” and is never estimated."
        actions={<LinkButton download href={downloadUrl(`/evaluations/${evaluationId}/reports/commercial`)}>Download Excel report</LinkButton>} />
      {excluded > 0 && <div className="mb-4"><Notice>{excluded} vendor(s) did not pass certification and are not commercially evaluated.</Notice></div>}
      {qualified.length === 0 ? <Empty>No vendor has passed the certification gate yet.</Empty> : (
        <div className="space-y-6">
          {qualified.map((v) => {
            const s = details.data!.commercial.find((c) => c.vendor_id === v.vendor_id);
            const rows = details.data!.findings.filter((f) => f.vendor_id === v.vendor_id && f.kind === "COMMERCIAL");
            return (
              <Card key={v.vendor_id} title={v.name} actions={<StatusBadge status={v.commercial.status} />}>
                {v.commercial.reason && <p className="mb-3 text-sm text-muted">{v.commercial.reason}</p>}
                {!s ? <Empty>No commercial evaluation recorded yet.</Empty> : (
                  <>
                    <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-4">
                      {([["Total price", money(s.data.total_price, s.data.currency)], ["Unit price", money(s.data.unit_price, s.data.currency)], ["Quantity", num(s.data.quantity)],
                        ["Taxes", typeof s.data.taxes_amount === "number" ? `${money(s.data.taxes_amount, s.data.currency)}${s.data.taxes_percent ? ` (${s.data.taxes_percent}%)` : ""}` : "not stated"],
                        ["Additional charges", money(s.data.additional_charges, s.data.currency)], ["Delivery", num(s.data.delivery_days, " days")], ["Payment terms", num(s.data.payment_days, " days")], ["Price validity", num(s.data.validity_days, " days")]] as const).map(([k, val]) => (
                        <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className={val === "not stated" ? "text-muted" : "font-medium"}>{val}</dd></div>
                      ))}
                    </dl>
                    {s.review_reasons.length > 0 && <ul className="mb-3 list-inside list-disc text-xs text-amber-800 dark:text-amber-300">{s.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
                  </>
                )}
                {rows.length > 0 && (
                  <Table head={["Condition", "Tender requires", "Vendor", "Result"]}>
                    {rows.map((f) => (
                      <tr key={f.criterion_code}>
                        <Td><div className="font-medium">{f.name}</div><div className="text-xs text-muted">{f.criterion_code}{f.mandatory ? "" : " · optional"}</div></Td>
                        <Td className="whitespace-nowrap">{reqText({ comparator: f.comparator as never, required_value: f.required_value, required_text: f.required_text, unit: f.unit })}</Td>
                        <Td className="text-xs">{f.evidence.supporting_text ? `“${f.evidence.supporting_text}”` : "—"}</Td>
                        <Td><StatusBadge status={f.status} /><div className="mt-1 text-xs text-muted">{f.reasons.join("; ")}</div></Td>
                      </tr>
                    ))}
                  </Table>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
