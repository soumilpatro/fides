import { createApiClient } from "./request";
import { ApiError } from "./errors";
import { connectionUuid } from "./connections";
import { boundedFetch } from "./dashboard";
import type { Currency, Person } from "./commitments";

export type DueRole="BORROWER"|"LENDER";
export type DueSummaryKind="upcoming"|"overdue";
export interface DueSummaryItem {
  commitment_id:string;
  counterparty:Person;
  role:DueRole;
  currency:Currency;
  verified_outstanding_minor:number;
  due_date:string;
  due_timezone:string;
  schedule_mode:"single"|"installments";
  installment_id:string|null;
}
export interface DueSummaryPage { items:DueSummaryItem[]; next_cursor:string|null }

const fail=():never=>{throw new ApiError("INVALID_RESPONSE","Unable to read the due-date summary.",null);};
const object=(v:unknown):Record<string,unknown>=>v&&typeof v==="object"&&!Array.isArray(v)?v as Record<string,unknown>:fail();
const uuid=(v:unknown)=>typeof v==="string"&&connectionUuid.test(v)?v:fail();
const text=(v:unknown)=>typeof v==="string"&&v.length>0?v:fail();
const date=(v:unknown)=>typeof v==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v+"T00:00:00Z"))?v:fail();
const dueRole=(v:unknown):DueRole=>v==="BORROWER"||v==="LENDER"?v:fail();
const currency=(v:unknown):Currency=>v==="INR"||v==="USD"||v==="GBP"?v:fail();
const scheduleMode=(v:unknown):DueSummaryItem["schedule_mode"]=>v==="single"||v==="installments"?v:fail();
const positiveMinor=(v:unknown):number=>typeof v==="number"&&Number.isSafeInteger(v)&&v>=1?v:fail();

export function dueSummaryItemResponse(value:unknown):DueSummaryItem{
  const row=object(value),person=object(row.counterparty);
  const role=dueRole(row.role),currencyCode=currency(row.currency),outstanding=positiveMinor(row.verified_outstanding_minor),mode=scheduleMode(row.schedule_mode);
  const installmentId=row.installment_id;
  if(installmentId!==null&&!(typeof installmentId==="string"&&connectionUuid.test(installmentId)))fail();
  if(mode==="single"&&installmentId!==null)fail();
  if(mode==="installments"&&installmentId===null)fail();
  return {
    commitment_id:uuid(row.commitment_id),
    counterparty:{id:uuid(person.id),display_name:text(person.display_name)},
    role,
    currency:currencyCode,
    verified_outstanding_minor:outstanding,
    due_date:date(row.due_date),
    due_timezone:text(row.due_timezone),
    schedule_mode:mode,
    installment_id:installmentId as string|null,
  };
}
export function dueSummaryPageResponse(value:unknown):DueSummaryPage{
  const row=object(value);
  const items=Array.isArray(row.items)?row.items:fail();
  const cursor=row.next_cursor;
  if(!(cursor===null||typeof cursor==="string"&&cursor.length>0&&cursor.length<=512&&!/[\u0000-\u001f\u007f]/.test(cursor)))fail();
  return {items:items.map(dueSummaryItemResponse),next_cursor:cursor as string|null};
}
export function appendDueSummary(previous:DueSummaryItem[],incoming:DueSummaryItem[]){
  const keys=new Set(previous.map(item=>(item.installment_id??item.commitment_id)+":"+item.due_date));
  return [...previous,...incoming.filter(item=>{const key=(item.installment_id??item.commitment_id)+":"+item.due_date;if(keys.has(key))return false;keys.add(key);return true;})];
}
export function createDueSummariesApi(config:Parameters<typeof createApiClient>[0]){
  const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)});
  return {list:async(kind:DueSummaryKind,options:{limit?:number;cursor?:string}={}):Promise<DueSummaryPage>=>{
    const limit=options.limit??50;
    if(!Number.isInteger(limit)||limit<1||limit>100)throw new ApiError("VALIDATION_ERROR","Invalid due-date summary request.",422);
    if(options.cursor!==undefined&&(!options.cursor.length||options.cursor.length>512||/[\u0000-\u001f\u007f]/.test(options.cursor)))throw new ApiError("VALIDATION_ERROR","Invalid due-date summary request.",422);
    const query=new URLSearchParams({limit:String(limit)});if(options.cursor!==undefined)query.set("cursor",options.cursor);
    return dueSummaryPageResponse(await request("/summary/"+kind+"?"+query),);
  }};
}
export type DueSummariesApi=ReturnType<typeof createDueSummariesApi>;
