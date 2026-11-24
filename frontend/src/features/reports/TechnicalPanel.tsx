"use client";

import { Badge, Card, Empty, ErrorBox, LinkButton, Notice, PageHeader, Spinner, StatusBadge, Table, Td } from "@/components/ui";
import { reqText } from "@/features/criteria/CriteriaPanel";
import { useApi } from "@/hooks/useApi";
import { downloadUrl } from "@/services/api";
import type { EvaluationDetails, Results } from "@/types/api";

export function TechnicalPanel({ evaluationId }: { evaluationId: string }) {
  const results = useApi<Results>(`/evaluations/${evaluationId}/results`, 5000);
  const details = useApi<EvaluationDetails>(`/evaluations/${evaluationId}/evaluation-details`, 5000);
  if (results.error) return <ErrorBox error={results.error} />;
  if (!results.data || !details.data) return <Spinner />;
  const qualified = results.data.vendors.filter((v) => v.eligibility === "PASS");
  const excluded = results.data.vendors.length - qualified.length;
  return (
    <>
      <PageHeader title="Technical evaluation" subtitle="Only vendors that passed certification screening appear here. Vendor values are quoted from their own quotation; comparison and scoring are deterministic."
        actions={<LinkButton download href={downloadUrl(`/evaluations/${evaluationId}/reports/technical`)}>Download Excel report</LinkButton>} />
      {excluded > 0 && <div className="mb-4"><Notice>{excluded} vendor(s) did not pass certification (failed or awaiting review) and are not technically evaluated. See Final results for their reasons.</Notice></div>}
      {qualified.length === 0 ? <Empty>No vendor has passed the certification gate yet.</Empty> : (
        <div className="space-y-6">
          {qualified.map((v) => {
            const rows = details.data!.findings.filter((f) => f.vendor_id === v.vendor_id && f.kind === "TECHNICAL");
            return (
              <Card key={v.vendor_id} title={v.name} actions={<><StatusBadge status={v.technical.status} />{v.technical.score != null && <Badge tone="blue">score {v.technical.score}%</Badge>}</>}>
                {v.technical.reason && <p className="mb-3 text-sm text-muted">{v.technical.reason}</p>}
                {rows.length === 0 ? <Empty>No technical comparison recorded{v.technical.status === "NOT_CONFIGURED" ? " (no confirmed technical criteria)" : " yet"}.</Empty> : (
                  <Table head={["Criterion", "Tender requires", "Vendor states", "Result", "Evidence"]}>
                    {rows.map((f) => (
                      <tr key={f.criterion_code}>
                        <Td><div className="font-medium">{f.name}</div><div className="text-xs text-muted">{f.criterion_code}{f.mandatory ? "" : " · optional"} · weight {f.weight}</div></Td>
                        <Td className="whitespace-nowrap">{reqText({ comparator: f.comparator as never, required_value: f.required_value, required_text: f.required_text, unit: f.unit })}{f.tender_page ? <div className="text-xs text-muted">tender p.{f.tender_page}</div> : null}</Td>
                        <Td>{f.evidence.vendor_value ?? "—"}</Td>
                        <Td><StatusBadge status={f.status} /><div className="mt-1 text-xs text-muted">{f.reasons.join("; ")}</div>{f.resolved_by && <div className="text-xs">resolved by {f.resolved_by}</div>}</Td>
                        <Td className="max-w-xs text-xs">{f.evidence.supporting_text ? <>“{f.evidence.supporting_text}”<div className="text-muted">{f.evidence.document_name} p.{f.evidence.page_number}</div></> : "—"}</Td>
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
