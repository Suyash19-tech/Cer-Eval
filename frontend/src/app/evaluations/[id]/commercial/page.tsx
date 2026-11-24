"use client";

import { useParams } from "next/navigation";
import { CommercialPanel } from "@/features/reports/CommercialPanel";

export default function CommercialPage() {
  const { id } = useParams<{ id: string }>();
  return <CommercialPanel evaluationId={id} />;
}
