import { createApiClient } from "./request";
import { boundedFetch } from "./dashboard";
import { array, object, text, uuid, stamp, person, identifier, key, invalidResponse } from "./f6-values";
import { validDate } from "../commitments/form";
import type { Person } from "./commitments";
export type ExtensionStatus="REQUESTED"|"ACCEPTED"|"REJECTED"|"CANCELLED";
export interface ExtensionRequest { requested_due_date:string; reason:string|null }
export interface Extension { id:string; commitment_id:string; requested_by:Person; status:ExtensionStatus; base_terms_version_id:string; previous_due_date:string; requested_due_date:string; reason:string|null; decided_by:Person|null; decided_at:string|null; created_at:string }
export function extensionResponse(v:unknown,parent:string):Extension {
 const r=object(v),status=text(r.status) as ExtensionStatus,previous=text(r.previous_due_date),requested=text(r.requested_due_date);
 if(!["REQUESTED","ACCEPTED","REJECTED","CANCELLED"].includes(status)||uuid(r.commitment_id)!==parent||!validDate(previous)||!validDate(requested)||requested<=previous)invalidResponse();
 const result={id:uuid(r.id),commitment_id:parent,requested_by:person(r.requested_by),status,base_terms_version_id:uuid(r.base_terms_version_id),previous_due_date:previous,requested_due_date:requested,reason:r.reason===null?null:text(r.reason),decided_by:r.decided_by===null?null:person(r.decided_by),decided_at:r.decided_at===null?null:stamp(r.decided_at),created_at:stamp(r.created_at)};
 if(status==="REQUESTED"&&(result.decided_by!==null||result.decided_at!==null))invalidResponse();
 if(["ACCEPTED","REJECTED"].includes(status)&&(!result.decided_by||!result.decided_at||result.decided_by.id===result.requested_by.id))invalidResponse();
 return result;
}
export function createExtensionsApi(config:Parameters<typeof createApiClient>[0]){
 const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)}),collection=(id:string)=>"/commitments/"+identifier(id)+"/extension-requests";
 return {
 listExtensions:async(id:string)=>array(await request(collection(id))).map(v=>extensionResponse(v,id)),
 requestExtension:async(id:string,body:ExtensionRequest,intentKey:string)=>extensionResponse(await request(collection(id),{method:"POST",body:{requested_due_date:body.requested_due_date,reason:body.reason},idempotencyKey:key(intentKey)}),id),
 acceptExtension:async(id:string,parent:string,intentKey:string)=>extensionResponse(await request("/extension-requests/"+identifier(id)+"/accept",{method:"POST",body:{},idempotencyKey:key(intentKey)}),parent),
 rejectExtension:async(id:string,parent:string,intentKey:string)=>extensionResponse(await request("/extension-requests/"+identifier(id)+"/reject",{method:"POST",body:{},idempotencyKey:key(intentKey)}),parent),
 };
}
export type ExtensionsApi=ReturnType<typeof createExtensionsApi>;
