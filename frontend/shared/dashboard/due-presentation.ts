import type { DueSummaryItem } from "../api/due-summaries";

export const dueRoleLabel=(item:DueSummaryItem)=>item.role==="BORROWER"?"Borrowed":"Lent";
export const dueDateLabel=(value:string)=>{
 const [year,month,day]=value.split("-").map(Number);
 return new Intl.DateTimeFormat("en",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(new Date(Date.UTC(year,month-1,day)));
};
export const dueInstallmentLabel=(item:DueSummaryItem)=>item.installment_id?"Installment due":"Commitment due";
