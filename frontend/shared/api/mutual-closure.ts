import { createApiClient } from "./request";
import { boundedFetch } from "./dashboard";
import { array, object, text, uuid, stamp, person, identifier, key, invalidResponse } from "./f6-values";
import type { Currency, Person } from "./commitments";

export type MutualClosureStatus="REQUESTED"|"ACCEPTED"|"REJECTED"|"CANCELLED";
export interface MutualClosureRequestBody { note:string|null }
export interface MutualClosure {
  id:string;
  commitment_id:string;
  requested_by:Person;
  counterparty:Person;
  status:MutualClosureStatus;
  currency:Currency;
  outstanding_snapshot_minor:number;
  waived_amount_minor:number;
  note:string|null;
  decided_by:Person|null;
  decided_at:string|null;
  created_at:string;
  updated_at:string;
}
const money=(v:unknown)=>typeof v==="number"&&Number.isSafeInteger(v)&&v>0?v:invalidResponse();
export function mutualClosureResponse(v:unknown,parent:string):MutualClosure{
  const r=object(v),status=text(r.status) as MutualClosureStatus,currency=text(r.currency) as Currency;
  if(!["REQUESTED","ACCEPTED","REJECTED","CANCELLED"].includes(status)||!["INR","USD","GBP"].includes(currency)||uuid(r.commitment_id)!==parent)invalidResponse();
  const result={
    id:uuid(r.id),commitment_id:parent,requested_by:person(r.requested_by),counterparty:person(r.counterparty),status,currency,
    outstanding_snapshot_minor:money(r.outstanding_snapshot_minor),waived_amount_minor:money(r.waived_amount_minor),
    note:r.note===null?null:text(r.note),decided_by:r.decided_by===null?null:person(r.decided_by),
    decided_at:r.decided_at===null?null:stamp(r.decided_at),created_at:stamp(r.created_at),updated_at:stamp(r.updated_at),
  };
  if(result.requested_by.id===result.counterparty.id)invalidResponse();
  if(status==="REQUESTED"&&(result.decided_by!==null||result.decided_at!==null))invalidResponse();
  if(status!=="REQUESTED"&&(!result.decided_by||!result.decided_at))invalidResponse();
  return result;
}
export function closureBody(note:string):MutualClosureRequestBody{
  const value=note.trim();
  if(Array.from(value).length>500)throw new Error("Note must be 500 characters or fewer.");
  return {note:value||null};
}
export function createMutualClosureApi(config:Parameters<typeof createApiClient>[0]){
  const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)});
  const collection=(id:string)=>"/commitments/"+identifier(id)+"/closure-requests";
  const action=(id:string,name:"accept"|"reject"|"cancel")=>"/closure-requests/"+identifier(id)+"/"+name;
  return {
    listClosureRequests:async(id:string)=>array(await request(collection(id))).map(v=>mutualClosureResponse(v,id)),
    getClosureRequest:async(id:string,parent:string)=>mutualClosureResponse(await request("/closure-requests/"+identifier(id)),parent),
    requestClosure:async(id:string,body:MutualClosureRequestBody,intentKey:string)=>mutualClosureResponse(await request(collection(id),{method:"POST",body,idempotencyKey:key(intentKey)}),id),
    acceptClosure:async(id:string,parent:string,intentKey:string)=>mutualClosureResponse(await request(action(id,"accept"),{method:"POST",body:{},idempotencyKey:key(intentKey)}),parent),
    rejectClosure:async(id:string,parent:string,intentKey:string)=>mutualClosureResponse(await request(action(id,"reject"),{method:"POST",body:{},idempotencyKey:key(intentKey)}),parent),
    cancelClosure:async(id:string,parent:string,intentKey:string)=>mutualClosureResponse(await request(action(id,"cancel"),{method:"POST",body:{},idempotencyKey:key(intentKey)}),parent),
  };
}
export type MutualClosureApi=ReturnType<typeof createMutualClosureApi>;
