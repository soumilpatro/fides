import { createApiClient } from "./request";
import { ApiError } from "./errors";
import { connectionUuid } from "./connections";
import { commitmentStatuses, type CommitmentStatus, type Currency, type Person } from "./commitments";
import { validDate } from "../commitments/form";
import { boundedFetch } from "./dashboard";
type RepaymentFacts = {repayment_id:string;amount_minor:number;currency:Currency};
type ExtensionFacts = {extension_request_id:string;base_terms_version_id:string;requested_by_user_id:string;previous_due_date:string;requested_due_date:string};
type ClosureFacts = {closure_request_id:string;currency:Currency;outstanding_snapshot_minor:number;waived_amount_minor:number};
type DetailMap = {
 COMMITMENT_PROPOSED:{status:"PENDING_CONFIRMATION";terms_version_id:string};
 COMMITMENT_CONFIRMED:{status:"ACTIVE"}; COMMITMENT_REJECTED:{status:"REJECTED"}; COMMITMENT_CANCELLED:{status:"CANCELLED"};
 REPAYMENT_REPORTED:RepaymentFacts & {terms_version_id:string;status:"PENDING_VERIFICATION"};
 REPAYMENT_VERIFIED:RepaymentFacts & {verification_id:string;terms_version_id:string;status:"VERIFIED";resulting_verified_outstanding_minor:number;resulting_commitment_status:CommitmentStatus};
 REPAYMENT_DISPUTED:RepaymentFacts & {verification_id:string;status:"DISPUTED"};
 EXTENSION_REQUESTED:ExtensionFacts & {status:"REQUESTED"};
 EXTENSION_ACCEPTED:ExtensionFacts & {status:"ACCEPTED";terms_version_id:string};
 EXTENSION_REJECTED:ExtensionFacts & {status:"REJECTED"};
 MUTUAL_CLOSURE_REQUESTED:ClosureFacts & {status:"REQUESTED"};
 MUTUAL_CLOSURE_ACCEPTED:ClosureFacts & {status:"ACCEPTED";resulting_commitment_status:"CLOSED"};
 MUTUAL_CLOSURE_REJECTED:ClosureFacts & {status:"REJECTED"};
 MUTUAL_CLOSURE_CANCELLED:ClosureFacts & {status:"CANCELLED"};
};
export type TimelineEvent = {[K in keyof DetailMap]:{id:string;commitment_id:string;actor:Person;occurred_at:string;event_type:K;details:DetailMap[K]}}[keyof DetailMap];
export interface LedgerResponse {items:TimelineEvent[];next_cursor:string|null}
const fail=():never=>{throw new ApiError("INVALID_RESPONSE","Unable to read the server history.",null);};
const object=(v:unknown):Record<string,unknown>=>v && typeof v==="object" && !Array.isArray(v)?v as Record<string,unknown>:fail();
const uuid=(v:unknown):string=>typeof v==="string"&&connectionUuid.test(v)?v:fail();
const string=(v:unknown):string=>typeof v==="string"?v:fail();
const money=(v:unknown,positive=false):number=>typeof v==="number"&&Number.isSafeInteger(v)&&v>=(positive?1:0)?v:fail();
function eventResponse(v:unknown,parent:string):TimelineEvent {
 const r=object(v),d=object(r.details),a=object(r.actor),type=string(r.event_type);
 const stamp=string(r.occurred_at);if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(stamp)||!Number.isFinite(Date.parse(stamp)))fail();
 if(uuid(r.commitment_id)!==parent)fail();
 let details:Record<string,unknown>;
 const statuses:Record<string,string>={COMMITMENT_PROPOSED:"PENDING_CONFIRMATION",COMMITMENT_CONFIRMED:"ACTIVE",COMMITMENT_REJECTED:"REJECTED",COMMITMENT_CANCELLED:"CANCELLED",REPAYMENT_REPORTED:"PENDING_VERIFICATION",REPAYMENT_VERIFIED:"VERIFIED",REPAYMENT_DISPUTED:"DISPUTED",EXTENSION_REQUESTED:"REQUESTED",EXTENSION_ACCEPTED:"ACCEPTED",EXTENSION_REJECTED:"REJECTED",MUTUAL_CLOSURE_REQUESTED:"REQUESTED",MUTUAL_CLOSURE_ACCEPTED:"ACCEPTED",MUTUAL_CLOSURE_REJECTED:"REJECTED",MUTUAL_CLOSURE_CANCELLED:"CANCELLED"};
 if(!Object.hasOwn(statuses,type)||d.status!==statuses[type])fail();
 if(type.startsWith("COMMITMENT_"))details={status:d.status,...(type==="COMMITMENT_PROPOSED"?{terms_version_id:uuid(d.terms_version_id)}:{})};
 else if(type.startsWith("REPAYMENT_")){
   if(!["INR","USD","GBP"].includes(string(d.currency)))fail();
   details={status:d.status,repayment_id:uuid(d.repayment_id),amount_minor:money(d.amount_minor,true),currency:d.currency};
   if(type!=="REPAYMENT_DISPUTED")details.terms_version_id=uuid(d.terms_version_id);
   if(type!=="REPAYMENT_REPORTED")details.verification_id=uuid(d.verification_id);
   if(type==="REPAYMENT_VERIFIED"){
     if(!commitmentStatuses.includes(d.resulting_commitment_status as CommitmentStatus))fail();
     details.resulting_commitment_status=d.resulting_commitment_status;
     details.resulting_verified_outstanding_minor=money(d.resulting_verified_outstanding_minor);
   }
 }else if(type.startsWith("EXTENSION_")){
   if(!validDate(string(d.previous_due_date))||!validDate(string(d.requested_due_date)))fail();
   details={status:d.status,extension_request_id:uuid(d.extension_request_id),base_terms_version_id:uuid(d.base_terms_version_id),requested_by_user_id:uuid(d.requested_by_user_id),previous_due_date:d.previous_due_date,requested_due_date:d.requested_due_date};
   if(type==="EXTENSION_ACCEPTED")details.terms_version_id=uuid(d.terms_version_id);
 }else{
   if(!["INR","USD","GBP"].includes(string(d.currency)))fail();
   details={status:d.status,closure_request_id:uuid(d.closure_request_id),currency:d.currency,outstanding_snapshot_minor:money(d.outstanding_snapshot_minor,true),waived_amount_minor:money(d.waived_amount_minor,true)};
   if(type==="MUTUAL_CLOSURE_ACCEPTED"){
     if(d.resulting_commitment_status!=="CLOSED")fail();
     details.resulting_commitment_status="CLOSED";
   }
 }
 return {id:uuid(r.id),commitment_id:parent,actor:{id:uuid(a.id),display_name:string(a.display_name)},occurred_at:stamp,event_type:type,details} as TimelineEvent;
}
export function ledgerResponse(value:unknown,parent:string):LedgerResponse {
 const r=object(value);if(!Array.isArray(r.items)||!(r.next_cursor===null||typeof r.next_cursor==="string"&&r.next_cursor.length>0&&r.next_cursor.length<=512))fail();
 return {items:(r.items as unknown[]).map(v=>eventResponse(v,parent)),next_cursor:r.next_cursor as string|null};
}
export function createLedgerApi(config:Parameters<typeof createApiClient>[0]){
 const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher)});
 return {getCommitmentLedger:async(id:string,options:{limit?:number;cursor?:string}={})=>{
  if(!connectionUuid.test(id))throw new ApiError("NOT_FOUND","Unavailable resource.",404);
  const limit=options.limit??50;
  if(!Number.isInteger(limit)||limit<1||limit>100||options.cursor!==undefined&&(typeof options.cursor!=="string"||options.cursor.length<1||options.cursor.length>512))throw new ApiError("VALIDATION_ERROR","Invalid history request.",422);
  const query=new URLSearchParams({limit:String(limit)});if(options.cursor!==undefined)query.set("cursor",options.cursor);
  return ledgerResponse(await request("/commitments/"+id+"/ledger?"+query),id);
 }};
}
export type LedgerApi=ReturnType<typeof createLedgerApi>;
