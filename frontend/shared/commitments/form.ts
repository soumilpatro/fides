import type { CommitmentRequest, Currency } from "../api/commitments";
import { parseBps, parseMinor } from "./money";
export interface ProposalForm {
  connection: string; role: "" | "BORROWER" | "LENDER"; type: "IOU" | "PEER_LOAN"; amount: string; currency: Currency;
  description: string; schedule: "none" | "single" | "installments"; due: string; dates: string[];
  interest: "NONE" | "SIMPLE_FIXED"; percent: string; grace: string;
}
export const initialForm = (connection = ""): ProposalForm => ({ connection, role: "", type: "IOU", amount: "", currency: "INR",
  description: "", schedule: "none", due: "", dates: ["", ""], interest: "NONE", percent: "", grace: "0" });
export function validDate(value: string) {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false;
  const [y,m,d] = value.split("-").map(Number);
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  return y > 0 && m >= 1 && m <= 12 && d >= 1 && d <= [31,leap?29:28,31,30,31,30,31,31,30,31,30,31][m-1];
}
export function proposalBody(form: ProposalForm, eligibleIds: string[]): CommitmentRequest {
  if (!eligibleIds.includes(form.connection)) throw new Error("Choose an accepted connection.");
  if (!["BORROWER", "LENDER"].includes(form.role)) throw new Error("Choose whether you are borrowing or lending.");
  if (!["IOU","PEER_LOAN"].includes(form.type) || !["INR","USD","GBP"].includes(form.currency)) throw new Error("Choose a supported type and currency.");
  const description = form.description.trim();
  if (Array.from(description).length > 500) throw new Error("Description must be at most 500 characters.");
  if (!/^[0-9]+$/.test(form.grace) || BigInt(form.grace) > 365n) throw new Error("Grace period must be an integer from 0 to 365.");
  let due_date: string | null = null, installment_dates: string[] | null = null;
  if (form.schedule === "single") { if (!validDate(form.due)) throw new Error("Enter a valid YYYY-MM-DD due date."); due_date = form.due; }
  else if (form.schedule === "installments") {
    if (form.dates.length < 2 || form.dates.length > 60 || form.dates.some(d => !validDate(d)) ||
      form.dates.some((d,i) => i > 0 && form.dates[i-1] >= d)) throw new Error("Use 2–60 valid installment dates in strictly increasing order.");
    installment_dates = [...form.dates];
  } else if (form.schedule !== "none") throw new Error("Choose a schedule.");
  if (!["NONE","SIMPLE_FIXED"].includes(form.interest)) throw new Error("Choose an interest type.");
  return { connection_id: form.connection, actor_role: form.role as "BORROWER" | "LENDER", type: form.type,
    principal_amount_minor: parseMinor(form.amount), currency: form.currency, description: description || null,
    terms: { due_date, installment_dates, interest_type: form.interest, interest_rate_bps: form.interest === "NONE" ? null : parseBps(form.percent), grace_period_days: Number(form.grace) } };
}
