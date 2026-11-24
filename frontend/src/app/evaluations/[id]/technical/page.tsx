"use client";

import { useParams } from "next/navigation";
import { TechnicalPanel } from "@/features/reports/TechnicalPanel";

export default function TechnicalPage() {
  const { id } = useParams<{ id: string }>();
  return <TechnicalPanel evaluationId={id} />;
}
