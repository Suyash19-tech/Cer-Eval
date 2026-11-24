"use client";

import { useParams } from "next/navigation";
import { CriteriaPanel } from "@/features/criteria/CriteriaPanel";
import { RequirementsPanel } from "@/features/requirements/RequirementsPanel";

export default function RequirementsPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="space-y-8">
      <RequirementsPanel evaluationId={id} />
      <CriteriaPanel evaluationId={id} />
    </div>
  );
}
