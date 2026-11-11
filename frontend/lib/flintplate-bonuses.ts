export interface BonusAgreement {
  id: string; supplier_id: string; reference: string; period_start: string; period_end: string;
  source_basis: "own_approved_invoice_net_before_credits"; rate_bps: number; threshold_cents: number;
  mode: "whole_base_at_threshold" | "excess_only"; currency: string; reason: string;
}
export interface BonusPreview {
  agreement_id: string; currency: string; period_start: string; period_end: string;
  sources: { invoice_id: string; purchase_line_id: string; issued_on: string; decided_at: string; quantity: string; net_cents: number }[];
  source_net_cents: number; claim_cents: number; already_stated_cents: number; delta_cents: number;
  fingerprint: string; blocking_reasons: string[];
}
export interface BonusStatement { id: string; agreement_id: string; sequence: number; delta_cents: number; snapshot: BonusPreview; created_at: string; reason: string }
export interface BonusDocument { original_issued_on: string; original_net_cents: number; original_tax_cents: number; status: "active" | "void"; version: number; effective_revision_id: string | null; id: string; supplier_id: string; reference: string; issued_on: string; net_cents: number; tax_cents: number; currency: string; allocated_cents: number; remaining_cents: number; reason: string }
export interface BonusAllocation { document_revision_id: string | null; id: string; document_id: string; agreement_id: string; amount_cents: number; created_at: string; reason: string }
export interface BonusBalance { agreement_id: string; claimed_cents: number; allocated_cents: number; remaining_cents: number }
export interface BonusReversal { id: string; allocation_id: string; document_id: string; document_revision_id: string | null; agreement_id: string; amount_cents: number; created_at: string; reason: string }
export interface BonusDocumentRevision { id: string; document_id: string; previous_revision_id: string | null; version: number; kind: "corrected" | "void"; issued_on: string; net_cents: number; tax_cents: number; created_at: string; reason: string }
export interface BonusSnapshot { reversals: BonusReversal[]; document_revisions: BonusDocumentRevision[]; agreements: BonusAgreement[]; statements: BonusStatement[]; documents: BonusDocument[]; allocations: BonusAllocation[]; balances: BonusBalance[] }
export const BONUS_PENDING_PREFIX = "flintplate:bonus-pending:v1:";
export const BONUS_PATHS = /^\/purchasing\/bonus-(agreements|statements|documents|allocations|allocations\/[a-f0-9-]+\/reverse|documents\/[a-f0-9-]+\/revisions)$/;
