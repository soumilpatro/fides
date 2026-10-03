import type { Commitment } from "../api/commitments";
import type { MutualClosure } from "../api/mutual-closure";
import type { Repayment } from "../api/repayments";

export type MutualClosureAction="accept"|"reject"|"cancel";

export function canRequestMutualClosure(parent:Commitment,rows:MutualClosure[]){
  return ["ACTIVE","PARTIALLY_REPAID"].includes(parent.status)&&!rows.some(row=>row.status==="REQUESTED");
}
export function mutualClosureActions(row:MutualClosure,user:string):MutualClosureAction[]{
  if(row.status!=="REQUESTED")return [];
  return row.requested_by.id===user?["cancel"]:row.counterparty.id===user?["accept","reject"]:[];
}
export const hasPendingRepayment=(rows:Repayment[])=>rows.some(row=>row.status==="PENDING_VERIFICATION");
export const verifiedRepayments=(rows:Repayment[])=>rows.filter(row=>row.status==="VERIFIED");
export const closureStatusLabel=(row:MutualClosure,user:string)=>
  row.status==="REQUESTED"?(row.requested_by.id===user?"Awaiting response":"Mutual closure requested"):
  row.status==="ACCEPTED"?"Closed by mutual agreement":
  row.status==="REJECTED"?"Mutual closure rejected":"Mutual closure cancelled";
