import { ApiError } from "./errors";
import { connectionUuid } from "./connections";
import type { Currency, Person } from "./commitments";

export type DueRole="BORROWER"|"LENDER";
export interface DueSummaryItem {
  commitment_id:string;
  counterparty:Person;
  role:DueRole;
  currency:Currency;
  verified_outstanding_minor:number;
  due_date:string;
  due_timezone:string;
  schedule_mode:string;
  installment_id:string|null;
}
export interface DueSummaryPage { items:DueSummaryItem[]; next_cursor:string|null }

const fail=():never=>{throw new ApiError("INVALID_RESPONSE","Unable to read the due-date summary.",null);};
const object=(v:unknown):Record<string,unknown>=>v&&typeof v==="object"&&!Array.isArray(v)?v as Record<string,unknown>:fail();
const uuid=(v:unknown)=>typeof v==="string"&&connectionUuid.test(v)?v:fail();
const text=(v:unknown)=>typeof v==="string"&&v.length>0?v:fail();
const date=(v:unknown)=>typeof v==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(v)?v:fail();

export function dueSummaryItemResponse(value:unknown):DueSummaryItem{
  const row=object(value),person=object(row.counterparty);
  const amount=row.verified_outstanding_minor;
  if(typeof amount!=="number"||!Number.isSafeInteger(amount)||amount<0)fail();
  if(row.role!=="BORROWER"&&row.role!=="LENDER")fail();
  if(row.currency!=="INR"&&row.currency!=="USD"&&row.currency!=="GBP")fail();
  if(row.installment_id!==null&&!(typeof row.installment_id==="string"&&connectionUuid.test(row.installment_id)))fail();
  return {
    commitment_id:uuid(row.commitment_id),
    counterparty:{id:uuid(person.id),display_name:text(person.display_name)},
    role:row.role,
    currency:row.currency,
    verified_outstanding_minor:amount,
    due_date:date(row.due_date),
    due_timezone:text(row.due_timezone),
    schedule_mode:text(row.schedule_mode),
    installment_id:row.installment_id as string|null,
  };
}
export function dueSummaryPageResponse(value:unknown):DueSummaryPage{
  const row=object(value);
  if(!Array.isArray(row.items))fail();
  const cursor=row.next_cursor;
  if(!(cursor===null||typeof cursor==="string"&&cursor.length>0&&cursor.length<=512))fail();
  return {items:row.items.map(dueSummaryItemResponse),next_cursor:cursor as string|null};
}

/*
 Live transport is intentionally NOT wired until the approved
 /summary/upcoming and /summary/overdue backend endpoints are merged.
 This decoder is the frozen frontend boundary for that contract.
*/
