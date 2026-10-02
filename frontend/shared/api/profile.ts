import { createApiClient } from "./request";
import { boundedFetch } from "./dashboard";
import { object, text, uuid, stamp, invalidResponse } from "./f6-values";
import type { CurrentUser } from "./types";
export interface ProfileUpdate { display_name?:string;timezone?:string }
export function meResponse(v:unknown):CurrentUser {
 const r=object(v);if(r.status!=="ACTIVE")invalidResponse();
 return {id:uuid(r.id),phone_e164:r.phone_e164===null?null:text(r.phone_e164),display_name:text(r.display_name),timezone:text(r.timezone),status:"ACTIVE",created_at:stamp(r.created_at),updated_at:stamp(r.updated_at)};
}
export function profileBody(v:ProfileUpdate):ProfileUpdate {
 const body:ProfileUpdate={};for(const field of ["display_name","timezone"] as const)if(v[field]!==undefined){if(typeof v[field]!=="string"||!v[field]!.trim())throw new Error("Enter "+field.replace("_"," ")+".");body[field]=v[field];}
 if(!Object.keys(body).length)throw new Error("Supply a profile change.");return body;
}
export function createProfileApi(config:Parameters<typeof createApiClient>[0]){
 const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)});
 return {
 updateProfile:async(body:ProfileUpdate)=>meResponse(await request("/me",{method:"PATCH",body:profileBody(body)})),
 deactivate:async()=>{const r=object(await request("/me/deactivate",{method:"POST",body:{}}));if(r.status!=="DEACTIVATED")invalidResponse();return {status:"DEACTIVATED" as const,deactivated_at:stamp(r.deactivated_at)};},
 };
}
export type ProfileApi=ReturnType<typeof createProfileApi>;
