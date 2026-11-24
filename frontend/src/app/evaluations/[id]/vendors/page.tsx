"use client";

import { useParams } from "next/navigation";
import { VendorsPanel } from "@/features/vendors/VendorsPanel";

export default function VendorsPage() {
  const { id } = useParams<{ id: string }>();
  return <VendorsPanel evaluationId={id} />;
}
