"use client";

import Link from "next/link";
import { Card, Empty, ErrorBox, LinkButton, PageHeader, Spinner, Stat, StatusBadge, Table, Td, formatDate } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import type { EvaluationSummary } from "@/types/api";

export default function Dashboard() {
  const { data, error, loading } = useApi<EvaluationSummary[]>("/evaluations", 10000);
  const sum = (k: "vendors" | "pass" | "fail" | "pending") => (data ?? []).reduce((a, e) => a + e[k], 0);
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Certification screening comes first. Only vendors that pass the eligibility gate reach technical and commercial evaluation."
        actions={<LinkButton href="/evaluations/new" variant="primary">New evaluation</LinkButton>} />
      {error && <ErrorBox error={error} />}
      {loading && <Spinner />}
      {data && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Evaluations" value={data.length} />
            <Stat label="Vendors" value={sum("vendors")} />
            <Stat label="Certification pass" value={sum("pass")} tone="text-green-700 dark:text-green-400" />
            <Stat label="Certification fail" value={sum("fail")} tone="text-red-700 dark:text-red-400" />
            <Stat label="Pending reviews" value={sum("pending")} tone="text-amber-700 dark:text-amber-400" />
          </div>
          <Card title="Recent evaluations">
            {data.length === 0 ? <Empty>No evaluations yet. Upload a tender to start.</Empty> : (
              <Table head={["Name", "Status", "Vendors", "Pass", "Fail", "Pending", "Created"]}>
                {data.slice(0, 20).map((e) => (
                  <tr key={e.id}>
                    <Td><Link className="font-medium underline-offset-2 hover:underline" href={`/evaluations/${e.id}/requirements`}>{e.name}</Link></Td>
                    <Td><StatusBadge status={e.workflow_status} /></Td>
                    <Td>{e.vendors}</Td><Td>{e.pass}</Td><Td>{e.fail}</Td><Td>{e.pending}</Td>
                    <Td className="text-muted">{formatDate(e.created_at)}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
