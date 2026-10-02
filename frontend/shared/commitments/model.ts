import type { Commitment, Terms, TermsVersion } from "../api/commitments";
import { ApiError } from "../api/errors";
export type ProposalAction = "confirm" | "reject" | "cancel";
export function commitmentRole(row: Commitment, userId: string) {
  const borrower = row.borrower.id === userId, lender = row.lender.id === userId;
  return borrower === lender || ![row.borrower.id, row.lender.id].includes(row.creator.id) ? null : borrower ? "Borrower" : "Lender";
}
export function counterparty(row: Commitment, userId: string) {
  const role = commitmentRole(row, userId); return role === null ? null : role === "Borrower" ? row.lender : row.borrower;
}
export function proposalActions(row: Commitment, userId: string): ProposalAction[] {
  if (!commitmentRole(row, userId) || row.status !== "PENDING_CONFIRMATION") return [];
  return row.creator.id === userId ? ["cancel"] : ["confirm", "reject"];
}
export const statusLabels = { DRAFT: "Draft", PENDING_CONFIRMATION: "Pending confirmation", CONFIRMED: "Confirmed", ACTIVE: "Active",
  PARTIALLY_REPAID: "Partially repaid", FULLY_REPAID: "Fully repaid", CLOSED: "Closed", REJECTED: "Rejected", CANCELLED: "Cancelled", DISPUTED: "Disputed", DEFAULTED: "Defaulted" };
export function proposalContext(row: Commitment, userId: string) {
  return row.status !== "PENDING_CONFIRMATION" ? statusLabels[row.status] :
    row.creator.id === userId ? "Awaiting confirmation" : "Needs your confirmation";
}
export function currentTerms(terms: Terms): TermsVersion {
  const current = terms.versions.find(v => v.id === terms.current_terms_version_id);
  if (!current) throw new ApiError("INVALID_RESPONSE", "Unable to read the server response.", null);
  return current;
}
export function scheduleText(v: TermsVersion) {
  return v.schedule_mode === "none" ? "No deadline" : v.schedule_mode === "single" ? "Due " + v.due_date : "Installment schedule";
}
export function proposalConfirmation(action: ProposalAction, name: string) {
  return action === "confirm" ? { title: "Confirm this commitment?", body: "Confirm that these terms match what you agreed with " + name + ".", button: "Confirm commitment" } :
    action === "reject" ? { title: "Reject this proposal?", body: "This proposal will be rejected. The existing record will remain available to its participants.", button: "Reject proposal" } :
    { title: "Cancel this proposal?", body: "This pending proposal will be cancelled.", button: "Cancel proposal" };
}
export function commitmentError(error: unknown, creating = false) {
  if (!(error instanceof ApiError)) return "Unable to confirm the result. Refresh before retrying the same request.";
  switch (error.code) {
    case "NOT_FOUND": return "This resource is unavailable.";
    case "FORBIDDEN": return "This action is not available to you.";
    case "INVALID_STATE": return creating ? "That connection can no longer be used for this commitment. Refresh and try again." : "This proposal cannot be changed in its current state. Refresh to see the current record.";
    case "IDEMPOTENCY_CONFLICT": return "This request conflicts with an earlier attempt. Refresh to reconcile; it will not be repeated with a new key.";
    case "INVALID_AMOUNT": return "Check the amount. The selected installment schedule may require a larger principal.";
    case "CURRENCY_MISMATCH": return "The currency does not match this record.";
    case "VALIDATION_ERROR": return "Check the proposal fields and terms.";
    default: return error.status === 401 ? "Your session needs attention. Please log in again." : "Unable to confirm the result. Refresh before retrying the same request.";
  }
}
