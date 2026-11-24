"use client";

import { useParams } from "next/navigation";
import { CertificationMatrix } from "@/features/reports/CertificationMatrix";

export default function CertificationPage() {
  const { id } = useParams<{ id: string }>();
  return <CertificationMatrix evaluationId={id} />;
}
