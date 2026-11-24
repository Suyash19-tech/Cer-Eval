// Mirrors the FastAPI response models. Statuses are strings produced by deterministic backend code.
export type Eligibility = "PASS" | "FAIL" | "PENDING_HUMAN_REVIEW";
export type ValidationStatus = "COMPLIANT" | "MISSING" | "EXPIRED" | "MISMATCH" | "NEEDS_HUMAN_REVIEW";

export interface Requirement {
  requirement_code: string;
  category: "X" | "Y" | "Z" | "OTHER_CERTIFICATION" | "ELIGIBILITY_CONDITION";
  description: string;
  mandatory: boolean;
  certificate_name: string | null;
  standard: string | null;
  version: string | null;
  validation_conditions: { conditions?: string[] } | null;
  source_page: number | null;
  supporting_text: string;
  needs_human_review: boolean;
  review_reasons: string[] | null;
  confirmed: boolean;
  rejected: boolean;
  origin: string;
}

export interface Evaluation {
  id: string;
  name: string;
  workflow_status: string;
  criteria_status: string;
  created_at: string;
  requirements_confirmed_at: string | null;
  requirements_confirmed_by: string | null;
  tender_sha256: string;
  error: string | null;
  requirements: Requirement[];
}

export interface EvaluationSummary {
  id: string;
  name: string;
  workflow_status: string;
  criteria_status: string;
  created_at: string;
  vendors: number;
  pass: number;
  fail: number;
  pending: number;
}

export interface Finding {
  requirement_code: string;
  mandatory: boolean;
  status: ValidationStatus;
  reasons: string[] | null;
  evidence: {
    document_id?: string;
    document_name?: string;
    page_number?: number;
    supporting_text?: string;
    expiry_text?: string | null;
    holder_name?: string | null;
    certificate_number?: string | null;
    issuer?: string | null;
    expiry_date?: string | null;
    version_found?: string | null;
  } | null;
  resolved_by: string | null;
}

export interface VendorDocument {
  id: string;
  filename: string;
  document_class: string;
  page_count: number | null;
  needs_flag: string | null;
}

export interface Vendor {
  id: string;
  evaluation_id: string;
  name: string;
  eligibility: Eligibility | null;
  eligibility_reason: string | null;
  screening_status: string;
  screening_error: string | null;
  created_at: string;
  documents: VendorDocument[];
  findings: Finding[];
}

export interface NodeLogEntry {
  node: string;
  status: string;
  ts: string;
  vendor_id?: string;
  [k: string]: unknown;
}

export interface WorkflowState {
  evaluation_id: string;
  started: boolean;
  status: string | null;
  workflow_status: string;
  error: string | null;
  awaiting_human_review: boolean;
  waiting_for: string[];
  pending_review: { vendor_id: string; name: string; reason: string }[];
  vendor_results: Record<string, Record<string, { status?: string; reason?: string; eligibility?: string }>>;
  downstream_done: string[];
  certification_reports: string[];
  errors: string[];
  node_log: NodeLogEntry[];
}

export interface StageResult {
  status: string;
  reason?: string;
  score?: number | null;
  total_price?: number | null;
  currency?: string | null;
}

export interface VendorResult {
  vendor_id: string;
  name: string;
  eligibility: Eligibility | null;
  eligibility_reason: string | null;
  technical: StageResult;
  commercial: StageResult;
  ranked: boolean;
  rank: number | null;
  combined_score: number | null;
  price_score: number | null;
  notes: string[];
}

export interface Results {
  vendors: VendorResult[];
  ranking: string[];
}

export interface Criterion {
  criterion_code: string;
  kind: "TECHNICAL" | "COMMERCIAL";
  name: string;
  parameter: string | null;
  comparator: "GTE" | "LTE" | "EQ" | "CONTAINS";
  required_value: number | null;
  required_text: string | null;
  unit: string | null;
  mandatory: boolean;
  weight: number;
  source_page: number | null;
  supporting_text: string;
  needs_human_review: boolean;
  review_reasons: string[] | null;
  confirmed: boolean;
  rejected: boolean;
}

export interface CriteriaState {
  criteria_status: string;
  config: Record<string, unknown> | null;
  criteria: Criterion[];
}

export interface CriterionFinding {
  vendor_id: string;
  vendor_name: string;
  kind: "TECHNICAL" | "COMMERCIAL";
  criterion_code: string;
  name: string;
  comparator: string | null;
  required_value: number | null;
  required_text: string | null;
  unit: string | null;
  tender_page: number | null;
  mandatory: boolean;
  weight: number;
  status: "MEETS" | "DEVIATES" | "MISSING_DETAIL" | "NEEDS_HUMAN_REVIEW";
  reasons: string[];
  evidence: { supporting_text?: string; document_name?: string; page_number?: number; document_id?: string; vendor_value?: number | null };
  resolved_by: string | null;
}

export interface CommercialSummaryRow {
  vendor_id: string;
  vendor_name: string;
  data: Record<string, number | string | null | Record<string, string>>;
  needs_human_review: boolean;
  review_reasons: string[];
}

export interface EvaluationDetails {
  findings: CriterionFinding[];
  commercial: CommercialSummaryRow[];
}
