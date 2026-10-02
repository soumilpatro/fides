import { ApiError } from "../api/errors";
import type { Commitment } from "../api/commitments";
import type { Repayment, Verification, RepaymentStatus, RepaymentRequest, DecisionRequest } from "../api/repayments";
import { commitmentRole } from "../commitments/model";
import { parseMinor } from "../commitments/money";
import { validDate } from "../commitments/form";
import type { SemanticStatus } from "../tokens/index";
export type DecisionAction = "verify" | "dispute";
export const labels: Record<RepaymentStatus,string> = {PENDING_VERIFICATION:"Pending verification",VERIFIED:"Verified",DISPUTED:"Disputed",CANCELLED:"Cancelled"};
export const semantics: Record<RepaymentStatus,SemanticStatus> = {PENDING_VERIFICATION:"PENDING",VERIFIED:"VERIFIED",DISPUTED:"DISPUTED",CANCELLED:"CLOSED"};
export function canReport(parent: Commitment, actor: string) { return !!commitmentRole(parent,actor) && ["ACTIVE","PARTIALLY_REPAID"].includes(parent.status); }
export function belongs(row: Repayment, parent: Commitment) { return row.commitment_id === parent.id && row.currency === parent.currency && [parent.borrower.id,parent.lender.id].includes(row.reported_by.id); }
export function canDecide(row: Repayment, parent: Commitment, actor: string) { return belongs(row,parent) && canReport(parent,actor) && row.status === "PENDING_VERIFICATION" && row.reported_by.id !== actor; }
export function coherentHistory(row: Repayment, parent: Commitment, history: Verification[]) {
  if (!belongs(row,parent) || history.some(h => h.repayment_id !== row.id || h.decided_by.id === row.reported_by.id || ![parent.borrower.id,parent.lender.id].includes(h.decided_by.id))) return false;
  if (row.status === "PENDING_VERIFICATION") return history.length === 0;
  if (row.status === "VERIFIED" || row.status === "DISPUTED") return history.length === 1 && history[0].decision === row.status;
  return true; // No cancellation mutation/history semantics are introduced by F4.
}
export function noteBody(value: string) { const note=value.trim(); if (Array.from(note).length > 500) throw new Error("Use at most 500 characters for the note."); return note || null; }
export function reportBody(form: { amount: string; date: string; note: string }, parent: Commitment): RepaymentRequest {
  if (!validDate(form.date)) throw new Error("Enter a valid payment date as YYYY-MM-DD.");
  return {amount_minor:parseMinor(form.amount),currency:parent.currency,payment_date:form.date,note:noteBody(form.note)};
}
export function decisionBody(note: string): DecisionRequest { return {decision_note:noteBody(note)}; }
export const decisionCopy = (action: DecisionAction) => action === "verify" ? {title:"Verify this repayment?",body:"Confirm that this repayment matches what you agreed.",support:"Verified repayments affect the commitment's recorded repayment state.",button:"Verify repayment",hint:"Add a note if useful."} : {title:"Dispute this repayment?",body:"Use this when the reported repayment does not match what you agreed.",support:"The record will show this repayment as disputed.",button:"Dispute repayment",hint:"Briefly explain what doesn't match."};
export function repaymentError(error: unknown) {
  if (!(error instanceof ApiError)) return "The outcome is uncertain. Refresh before explicitly retrying the same request.";
  const messages: Record<string,string> = {
    OVER_REPAYMENT:"The server cannot accept this amount under the current terms and repayment records. Refresh the record; no remaining amount has been estimated.",
    INVALID_STATE:"This record is no longer eligible for that action. Refresh to see its current state.",
    ALREADY_VERIFIED:"This repayment has already been verified. Refresh its record and history.",
    IDEMPOTENCY_CONFLICT:"This request key conflicts with an earlier payload. Refresh to reconcile; do not submit a replacement request.",
    CONFLICT:"Another request may be in progress. Refresh before retrying the same request.",
    NOT_FOUND:"Unavailable resource.",FORBIDDEN:"You cannot perform this action on this repayment.",
    VALIDATION_ERROR:"Check the amount, date and optional note. The payment date must not be in the future in your account timezone.",
    INVALID_AMOUNT:"Enter a positive amount with up to two fractional digits.",CURRENCY_MISMATCH:"The repayment currency must match the commitment. Refresh its record.",
  };
  return messages[error.code] ?? (error.status === 401 ? "Your session needs to be resolved before continuing." : error.status === null || error.status >= 500 ? "The outcome could not be confirmed. Refresh before explicitly retrying the same request." : "Unable to continue. Refresh the record and try again.");
}
