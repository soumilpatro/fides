import { createApiClient } from "./request";
import { ApiError } from "./errors";
import { connectionUuid } from "./connections";
export type Currency = "INR" | "USD" | "GBP";
export const commitmentStatuses = ["DRAFT", "PENDING_CONFIRMATION", "CONFIRMED", "ACTIVE", "PARTIALLY_REPAID", "FULLY_REPAID", "CLOSED", "REJECTED", "CANCELLED", "DISPUTED", "DEFAULTED"] as const;
export type CommitmentStatus = typeof commitmentStatuses[number];
export interface Person { id: string; display_name: string }
export interface TermsRequest {
  due_date: string | null; interest_type: "NONE" | "SIMPLE_FIXED"; interest_rate_bps: number | null;
  grace_period_days: number; installment_dates: string[] | null;
}
export interface CommitmentRequest {
  connection_id: string; actor_role: "BORROWER" | "LENDER"; type: "IOU" | "PEER_LOAN";
  principal_amount_minor: number; currency: Currency; description: string | null; terms: TermsRequest;
}
export interface Commitment {
  id: string; connection_id: string; type: "IOU" | "PEER_LOAN"; status: CommitmentStatus;
  principal_amount_minor: number; currency: Currency; description: string | null;
  borrower: Person; lender: Person; creator: Person; created_at: string; updated_at: string;
  confirmed_at: string | null; activated_at: string | null;
}
export interface TermsVersion extends TermsRequest {
  id: string; version_no: number; effective_at: string; created_at: string;
  schedule_mode: "none" | "single" | "installments"; due_timezone: string | null; created_by: Person;
}
export interface Terms {
  commitment_id: string; currency: Currency; current_terms_version_id: string; versions: TermsVersion[];
}
export interface Installment {
  id: string; terms_version_id: string; sequence_no: number; due_date: string;
  principal_amount_minor: number; interest_amount_minor: number; total_due_minor: number;
  currency: Currency; status: "PENDING" | "PARTIALLY_PAID" | "PAID" | "OVERDUE" | "CANCELLED";
  created_at: string; updated_at: string;
}
const fail = (): never => { throw new ApiError("INVALID_RESPONSE", "Unable to read the server response.", null); };
function object(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : fail(); }
const string = (v: unknown): string => typeof v === "string" ? v : fail();
const nullable = (v: unknown) => v === null ? null : string(v);
const uuid = (v: unknown): string => typeof v === "string" && connectionUuid.test(v) ? v : fail();
const integer = (v: unknown): number => typeof v === "number" && Number.isSafeInteger(v) ? v : fail();
const timestamp = (v: unknown): string => typeof v === "string" && Number.isFinite(Date.parse(v)) ? v : fail();
const maybeTimestamp = (v: unknown) => v === null ? null : timestamp(v);
function choice<T extends string>(v: unknown, values: readonly T[]): T { return typeof v === "string" && values.includes(v as T) ? v as T : fail(); }
const currency = (v: unknown) => choice(v, ["INR", "USD", "GBP"] as const);
const date = (v: unknown) => typeof v === "string" && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(v) ? v : fail();
const array = (v: unknown): unknown[] => Array.isArray(v) ? v : fail();
const person = (v: unknown): Person => { const p = object(v); return { id: uuid(p.id), display_name: string(p.display_name) }; };
export function commitmentResponse(value: unknown): Commitment {
  const r = object(value);
  const amount = integer(r.principal_amount_minor); if (amount <= 0 || amount > 1_000_000_000_000) fail();
  return { id: uuid(r.id), connection_id: uuid(r.connection_id), type: choice(r.type, ["IOU", "PEER_LOAN"]),
    status: choice(r.status, commitmentStatuses), principal_amount_minor: amount, currency: currency(r.currency),
    description: nullable(r.description), borrower: person(r.borrower), lender: person(r.lender), creator: person(r.creator),
    created_at: timestamp(r.created_at), updated_at: timestamp(r.updated_at), confirmed_at: maybeTimestamp(r.confirmed_at), activated_at: maybeTimestamp(r.activated_at) };
}
export function termsResponse(value: unknown): Terms {
  const r = object(value);
  const versions = array(r.versions).map(value => {
    const v = object(value);
    return { id: uuid(v.id), version_no: integer(v.version_no), effective_at: timestamp(v.effective_at), created_at: timestamp(v.created_at),
      due_date: v.due_date === null ? null : date(v.due_date), interest_type: choice(v.interest_type, ["NONE", "SIMPLE_FIXED"] as const),
      interest_rate_bps: v.interest_rate_bps === null ? null : integer(v.interest_rate_bps), grace_period_days: integer(v.grace_period_days),
      schedule_mode: choice(v.schedule_mode, ["none", "single", "installments"] as const), due_timezone: nullable(v.due_timezone),
      installment_dates: v.installment_dates === null ? null : array(v.installment_dates).map(date), created_by: person(v.created_by) };
  });
  const current = uuid(r.current_terms_version_id);
  if (!versions.some(v => v.id === current)) fail();
  return { commitment_id: uuid(r.commitment_id), currency: currency(r.currency), current_terms_version_id: current, versions };
}
export function installmentResponse(value: unknown): Installment {
  const r = object(value);
  const result = { id: uuid(r.id), terms_version_id: uuid(r.terms_version_id), sequence_no: integer(r.sequence_no), due_date: date(r.due_date),
    principal_amount_minor: integer(r.principal_amount_minor), interest_amount_minor: integer(r.interest_amount_minor),
    total_due_minor: integer(r.total_due_minor), currency: currency(r.currency),
    status: choice(r.status, ["PENDING", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED"] as const),
    created_at: timestamp(r.created_at), updated_at: timestamp(r.updated_at) };
  if (result.sequence_no < 1 || result.principal_amount_minor < 0 || result.interest_amount_minor < 0 || result.total_due_minor <= 0) fail();
  return result;
}
export function createCommitmentsApi(config: Parameters<typeof createApiClient>[0]) {
  const fetcher: typeof fetch = async (input, init) => {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15000);
    try { return await (config.fetcher ?? fetch)(input, { ...init, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  };
  const request = createApiClient({ ...config, fetcher });
  const path = (id: string) => { if (!connectionUuid.test(id)) throw new ApiError("NOT_FOUND", "Unavailable resource.", 404); return "/commitments/" + id; };
  const key = (value: string) => { if (!/^[A-Za-z0-9._:-]{1,128}$/.test(value)) throw new ApiError("MALFORMED_REQUEST", "Invalid request.", 400); return value; };
  const result = async (value: Promise<unknown>) => commitmentResponse(await value);
  return {
    createCommitment: (body: CommitmentRequest, idempotencyKey: string) => result(request("/commitments", { method: "POST", body, idempotencyKey: key(idempotencyKey) })),
    listCommitments: async () => array(await request("/commitments")).map(commitmentResponse),
    getCommitment: (id: string) => result(request(path(id))),
    confirmCommitment: (id: string, idempotencyKey: string) => result(request(path(id) + "/confirm", { method: "POST", idempotencyKey: key(idempotencyKey) })),
    rejectCommitment: (id: string, idempotencyKey: string) => result(request(path(id) + "/reject", { method: "POST", idempotencyKey: key(idempotencyKey) })),
    cancelCommitment: (id: string, idempotencyKey: string) => result(request(path(id) + "/cancel", { method: "POST", idempotencyKey: key(idempotencyKey) })),
    getCommitmentTerms: async (id: string) => termsResponse(await request(path(id) + "/terms")),
    getCommitmentInstallments: async (id: string) => array(await request(path(id) + "/installments")).map(installmentResponse),
  };
}
export type CommitmentsApi = ReturnType<typeof createCommitmentsApi>;
