import { createApiClient } from "./request";
import { ApiError } from "./errors";
import { connectionUuid } from "./connections";
import type { Currency, Person } from "./commitments";
import { validDate } from "../commitments/form";
export const repaymentStatuses = ["PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CANCELLED"] as const;
export type RepaymentStatus = typeof repaymentStatuses[number];
export interface RepaymentRequest { amount_minor: number; currency: Currency; payment_date: string; note: string | null }
export interface DecisionRequest { decision_note: string | null }
export interface Repayment { id: string; commitment_id: string; reported_by: Person; amount_minor: number; currency: Currency; payment_date: string; reported_at: string; status: RepaymentStatus; note: string | null; created_at: string }
export interface Verification { id: string; repayment_id: string; decided_by: Person; decision: "VERIFIED" | "DISPUTED"; decision_note: string | null; decided_at: string }
const fail = (): never => { throw new ApiError("INVALID_RESPONSE", "Unable to read the server response.", null); };
const object = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : fail();
const string = (v: unknown): string => typeof v === "string" ? v : fail();
const uuid = (v: unknown) => typeof v === "string" && connectionUuid.test(v) ? v : fail();
const stamp = (v: unknown) => typeof v === "string" && Number.isFinite(Date.parse(v)) ? v : fail();
const nullable = (v: unknown) => v === null ? null : string(v);
const person = (v: unknown): Person => { const p = object(v); return { id: uuid(p.id), display_name: string(p.display_name) }; };
function choice<T extends string>(v: unknown, values: readonly T[]): T { return typeof v === "string" && values.includes(v as T) ? v as T : fail(); }
const array = (v: unknown): unknown[] => Array.isArray(v) ? v : fail();
export function repaymentResponse(value: unknown): Repayment {
  const r = object(value), amount = r.amount_minor;
  if (typeof amount !== "number" || !Number.isSafeInteger(amount) || amount <= 0) fail();
  const date = string(r.payment_date); if (!validDate(date)) fail();
  return { id: uuid(r.id), commitment_id: uuid(r.commitment_id), reported_by: person(r.reported_by), amount_minor: amount as number,
    currency: choice(r.currency, ["INR","USD","GBP"]), payment_date: date, reported_at: stamp(r.reported_at), status: choice(r.status, repaymentStatuses), note: nullable(r.note), created_at: stamp(r.created_at) };
}
export function verificationResponse(value: unknown): Verification {
  const r = object(value); return { id: uuid(r.id), repayment_id: uuid(r.repayment_id), decided_by: person(r.decided_by),
    decision: choice(r.decision,["VERIFIED","DISPUTED"]), decision_note: nullable(r.decision_note), decided_at: stamp(r.decided_at) };
}
export function createRepaymentsApi(config: Parameters<typeof createApiClient>[0]) {
  const fetcher: typeof fetch = async (input, init) => {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(),15000);
    try { return await (config.fetcher ?? fetch)(input,{...init,signal:controller.signal}); } finally { clearTimeout(timer); }
  };
  const request = createApiClient({...config,fetcher});
  const identifier = (id: string) => { if (!connectionUuid.test(id)) throw new ApiError("NOT_FOUND","Unavailable resource.",404); return id; };
  const key = (value: string) => { if (!/^[A-Za-z0-9._:-]{1,128}$/.test(value)) throw new ApiError("MALFORMED_REQUEST","Invalid request.",400); return value; };
  const repayment = (id: string) => "/repayments/" + identifier(id);
  const collection = (id: string) => "/commitments/" + identifier(id) + "/repayments";
  const result = async (value: Promise<unknown>) => repaymentResponse(await value);
  return {
    reportRepayment: (id: string, body: RepaymentRequest, idempotencyKey: string) => result(request(collection(id),{method:"POST",body:{amount_minor:body.amount_minor,currency:body.currency,payment_date:body.payment_date,note:body.note},idempotencyKey:key(idempotencyKey)})),
    listRepayments: async (id: string) => array(await request(collection(id))).map(repaymentResponse),
    getRepayment: (id: string) => result(request(repayment(id))),
    verifyRepayment: (id: string, body: DecisionRequest, idempotencyKey: string) => result(request(repayment(id)+"/verify",{method:"POST",body:{decision_note:body.decision_note},idempotencyKey:key(idempotencyKey)})),
    disputeRepayment: (id: string, body: DecisionRequest, idempotencyKey: string) => result(request(repayment(id)+"/dispute",{method:"POST",body:{decision_note:body.decision_note},idempotencyKey:key(idempotencyKey)})),
    getVerificationHistory: async (id: string) => array(await request(repayment(id)+"/verification-history")).map(verificationResponse),
  };
}
export type RepaymentsApi = ReturnType<typeof createRepaymentsApi>;
