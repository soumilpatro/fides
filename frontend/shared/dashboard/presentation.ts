import type { TimelineEvent } from "../api/ledger";
import { formatMoney } from "../domain/money";
import type { CurrencySummary } from "../api/dashboard";
export const netText=(row:CurrencySummary)=>(row.net_position_minor>0?"+":"")+formatMoney(row.net_position_minor,row.currency);
export const netMeaning=(value:number)=>value>0?"Lent outstanding exceeds borrowed outstanding.":value<0?"Borrowed outstanding exceeds lent outstanding.":"Lent and borrowed outstanding are equal.";
export function historyText(event:TimelineEvent){
 switch(event.event_type){
 case "COMMITMENT_PROPOSED":return "Proposed this commitment.";
 case "COMMITMENT_CONFIRMED":return "Confirmed this commitment.";
 case "COMMITMENT_REJECTED":return "Rejected this proposal.";
 case "COMMITMENT_CANCELLED":return "Cancelled this proposal.";
 case "REPAYMENT_REPORTED":return "Reported a repayment of "+formatMoney(event.details.amount_minor,event.details.currency)+".";
 case "REPAYMENT_VERIFIED":return "Verified a repayment of "+formatMoney(event.details.amount_minor,event.details.currency)+".";
 case "REPAYMENT_DISPUTED":return "Disputed a repayment of "+formatMoney(event.details.amount_minor,event.details.currency)+".";
 default:return "Recorded a due-date change: "+event.details.status.toLowerCase()+".";
 }
}
export function appendHistory(previous:TimelineEvent[],incoming:TimelineEvent[]){
 const ids=new Set(previous.map(row=>row.id));return [...previous,...incoming.filter(row=>{if(ids.has(row.id))return false;ids.add(row.id);return true;})];
}
