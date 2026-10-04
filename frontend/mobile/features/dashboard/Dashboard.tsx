import { useState } from "react";
import { netMeaning,netText,historyText } from "@fides/shared/dashboard/presentation";
import { counterparty,statusLabels } from "@fides/shared/commitments/model";
import { Amount,Body,Button,Card,LoadingState,ErrorState,EmptyState,StatusChip,Screen,Title } from "../../components/ui";
import { useDashboard } from "./useDashboard";
import { useHistory } from "./useHistory";
import { useCommitments } from "../commitments/useCommitments";
import { RepaymentDetail } from "../repayments/Repayments";
export function Summary(){
 const data=useDashboard();
 return <><Card title="Verified outstanding"><Body supporting>Current server summary, based on verified repayments. Currencies remain separate.</Body><Button title="Refresh summary" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/></Card>
 {data.busy&&<LoadingState message="Loading verified outstanding…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data?.currencies.map(row=><Card key={row.currency} title={row.currency}><Body>Borrowed outstanding</Body><Amount minor={row.borrowed_outstanding_minor} currency={row.currency} size="row"/><Body>Lent outstanding</Body><Amount minor={row.lent_outstanding_minor} currency={row.currency} size="row"/><Body>Net position</Body><Body>{netText(row)}</Body><Body supporting>{netMeaning(row.net_position_minor)}</Body></Card>)}</>;
}
export function History({id,onRepayment}:{id:string;onRepayment:(id:string)=>void}){
 const data=useHistory(id);
 return <><Card title="Commitment history"><Body supporting>Oldest first. History loads in live pages; it is not a fixed snapshot.</Body><Button title="Refresh history" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/></Card>
 {data.busy&&<LoadingState message="Loading commitment history…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data?.items.length===0&&<Body>No history available yet.</Body>}
 {data.data?.items.map(event=><Card key={event.id} title={event.actor.display_name}><Body>{historyText(event)}</Body><Body supporting>{new Date(event.occurred_at).toLocaleString()}</Body>
 {"repayment_id" in event.details&&<><StatusChip label={event.details.status==="PENDING_VERIFICATION"?"Pending verification":event.details.status==="VERIFIED"?"Verified":"Disputed"} status={event.details.status==="PENDING_VERIFICATION"?"PENDING":event.details.status==="VERIFIED"?"VERIFIED":"DISPUTED"}/><Button title="View repayment" variant="quiet" onPress={()=>{if("repayment_id" in event.details)onRepayment(event.details.repayment_id);}}/></>}
 {event.event_type==="REPAYMENT_VERIFIED"&&<Body>Verified outstanding after this event</Body><Amount minor={event.details.resulting_verified_outstanding_minor} currency={event.details.currency} size="row"/>}</Card>)}
 {data.data?.next_cursor&&<Button title="Load more history" disabled={data.busy} onPress={()=>void data.loadMore()}/>}</>;
}
export function Activity({onCreate}:{onCreate:()=>void}){
 const [selected,setSelected]=useState<string|null>(null),[repayment,setRepayment]=useState<string|null>(null);
 if(repayment)return <RepaymentDetail key={repayment} id={repayment} onBack={()=>setRepayment(null)}/>;
 if(selected)return <SelectedHistory key={selected} id={selected} onBack={()=>setSelected(null)} onRepayment={setRepayment}/>;
 return <HistoryIndex onCreate={onCreate} onSelect={setSelected}/>;
}
function HistoryIndex({onCreate,onSelect}:{onCreate:()=>void;onSelect:(id:string)=>void}){
 const data=useCommitments();
 return <Screen><Title>Activity</Title><Body>Activity is recorded separately for each commitment.</Body><Button title="Refresh commitments" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/>
 {data.busy&&<LoadingState message="Loading your commitments…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data?.rows.length===0&&<><EmptyState title="No activity yet" message="Activity appears within your commitments as you and the other participant record changes."/><Button title="Create commitment" onPress={onCreate}/></>}
 {data.data?.rows.map(row=><Card key={row.id} title={counterparty(row,data.userId)!.display_name}><Body>{row.type==="IOU"?"IOU":"Peer loan"}</Body><Amount minor={row.principal_amount_minor} currency={row.currency} size="row"/><StatusChip label={statusLabels[row.status]}/><Button title={"View history with "+counterparty(row,data.userId)!.display_name} variant="quiet" onPress={()=>onSelect(row.id)}/></Card>)}</Screen>;
}
function SelectedHistory({id,onBack,onRepayment}:{id:string;onBack:()=>void;onRepayment:(id:string)=>void}){
 const data=useCommitments(id),row=data.data?.detail;
 return <Screen><Button title="Back to Activity" variant="quiet" onPress={onBack}/><Title>Commitment history</Title>{data.busy&&<LoadingState message="Loading the commitment…"/>}{data.error&&<ErrorState message={data.error}/>}
 {row&&<><Card title={counterparty(row,data.userId)!.display_name}><Amount minor={row.principal_amount_minor} currency={row.currency} size="row"/><StatusChip label={statusLabels[row.status]}/></Card><History key={id} id={id} onRepayment={onRepayment}/></>}</Screen>;
}
