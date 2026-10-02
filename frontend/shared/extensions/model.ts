import type { Commitment, Terms } from "../api/commitments";
import type { Extension, ExtensionRequest } from "../api/extensions";
import { currentTerms } from "../commitments/model";
import { validDate } from "../commitments/form";
export function canRequestExtension(parent:Commitment,terms:Terms,rows:Extension[]){
 return ["ACTIVE","PARTIALLY_REPAID"].includes(parent.status)&&currentTerms(terms).schedule_mode==="single"&&!rows.some(r=>r.status==="REQUESTED");
}
export function extensionActions(row:Extension,user:string,parent:Commitment,terms:Terms):("accept"|"reject")[]{
 if(row.status!=="REQUESTED"||row.requested_by.id===user||![parent.borrower.id,parent.lender.id].includes(user))return [];
 const current=currentTerms(terms);return ["ACTIVE","PARTIALLY_REPAID"].includes(parent.status)&&current.schedule_mode==="single"?["accept","reject"]:["reject"];
}
export function extensionBody(date:string,reason:string,current:string):ExtensionRequest {
 if(!validDate(date)||date<=current)throw new Error("Choose a date later than the current due date.");
 const value=reason.trim();if(Array.from(value).length>500)throw new Error("Reason must contain at most 500 characters.");
 return {requested_due_date:date,reason:value||null};
}
export const staleExtension="The commitment terms changed after this extension was requested. Refresh before deciding.";
