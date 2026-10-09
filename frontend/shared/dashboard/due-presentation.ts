import type { DueSummaryItem } from "../api/due-summaries";

export const dueRoleLabel=(item:DueSummaryItem)=>item.role==="BORROWER"?"Borrowed":"Lent";
export const dateOnlyLabel=(value:string)=>{
 const [year,month,day]=value.split("-").map(Number);
 return new Intl.DateTimeFormat("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(new Date(Date.UTC(year,month-1,day)));
};
export const dueDateLabel=dateOnlyLabel;
export const dueInstallmentLabel=(item:DueSummaryItem)=>item.installment_id?"Installment due":"Commitment due";
