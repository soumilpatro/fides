import { createApiClient } from "./request";
import { ApiError } from "./errors";
import type { Currency } from "./commitments";
export interface CurrencySummary { currency: Currency; borrowed_outstanding_minor: number; lent_outstanding_minor: number; net_position_minor: number }
export interface SummaryResponse { currencies: [CurrencySummary, CurrencySummary, CurrencySummary] }
export function summaryResponse(value: unknown): SummaryResponse {
  const fail = (): never => { throw new ApiError("INVALID_RESPONSE","Unable to read the server summary.",null); };
  if (!value || typeof value !== "object" || !("currencies" in value) || !Array.isArray(value.currencies) || value.currencies.length !== 3) return fail();
  const currencies = value.currencies.map((v: unknown,index: number) => {
    if (!v || typeof v !== "object") return fail();
    const r = v as Record<string,unknown>;
    if (r.currency !== ["INR","USD","GBP"][index]) return fail();
    for (const key of ["borrowed_outstanding_minor","lent_outstanding_minor","net_position_minor"]) {
      if (typeof r[key] !== "number" || !Number.isSafeInteger(r[key]) || (key !== "net_position_minor" && (r[key] as number) < 0)) return fail();
    }
    return {currency:r.currency as Currency,borrowed_outstanding_minor:r.borrowed_outstanding_minor as number,lent_outstanding_minor:r.lent_outstanding_minor as number,net_position_minor:r.net_position_minor as number};
  });
  // Display server net directly; no local accounting or cross-currency total.
  return {currencies:currencies as SummaryResponse["currencies"]};
}
export function createDashboardApi(config: Parameters<typeof createApiClient>[0]) {
  const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher)});
  return {getSummary:async () => summaryResponse(await request("/summary"))};
}
export function boundedFetch(fetcher: typeof fetch = fetch): typeof fetch {
  return async (input,init) => { const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try {return await fetcher(input,{...init,signal:controller.signal});} finally {clearTimeout(timer);} };
}
export type DashboardApi = ReturnType<typeof createDashboardApi>;
