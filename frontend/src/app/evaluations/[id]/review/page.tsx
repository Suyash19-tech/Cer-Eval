"use client";

import { useParams } from "next/navigation";
import { ReviewPanel } from "@/features/review/ReviewPanel";

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  return <ReviewPanel evaluationId={id} />;
}
