"use client";

import { useParams } from "next/navigation";
import { ScreeningPanel } from "@/features/workflow/ScreeningPanel";

export default function ScreeningPage() {
  const { id } = useParams<{ id: string }>();
  return <ScreeningPanel evaluationId={id} />;
}
