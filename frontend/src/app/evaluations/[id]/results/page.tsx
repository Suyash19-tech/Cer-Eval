"use client";

import { useParams } from "next/navigation";
import { ResultsPanel } from "@/features/reports/ResultsPanel";

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  return <ResultsPanel evaluationId={id} />;
}
