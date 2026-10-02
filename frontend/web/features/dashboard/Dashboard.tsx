"use client";
import Link from "next/link";
import { formatMoney } from "@fides/shared/domain/money";
import { netMeaning,netText,historyText } from "@fides/shared/dashboard/presentation";
import { counterparty,statusLabels } from "@fides/shared/commitments/model";
import { Button,Card,LoadingState,ErrorState,EmptyState,StatusChip } from "../../components/ui";
import { useDashboard } from "./useDashboard";
import { useHistory } from "./useHistory";
import { useCommitments } from "../commitments/useCommitments";
export function Summary(){
 const data=useDashboard();
 return <section aria-labelledby="summary-title" className="commitments-feature"><h2 id="summary-title">Verified outstanding</h2><p className="supporting">Current server summary, based on verified repayments. Currencies remain separate.</p>
 <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh summary</Button>
 {data.busy&&<LoadingState message="Loading verified outstanding…"/>}{data.error&&<ErrorState message={data.error}/>}
 <div className="summary-grid">{data.data?.currencies.map(row=><Card key={row.currency} title={row.currency}><dl className="commitment-facts">
 <dt>Borrowed outstanding</dt><dd className="amount">{formatMoney(row.borrowed_outstanding_minor,row.currency)}</dd>
 <dt>Lent outstanding</dt><dd className="amount">{formatMoney(row.lent_outstanding_minor,row.currency)}</dd>
 <dt>Net position</dt><dd className="amount">{netText(row)}</dd></dl><p className="supporting">{netMeaning(row.net_position_minor)}</p></Card>)}</div></section>;
}
export function History({id}:{id:string}){
 const data=useHistory(id);
 return <section aria-labelledby={"history-"+id} className="commitments-feature"><h2 id={"history-"+id}>Commitment history</h2><p className="supporting">Oldest first. History loads in live pages; it is not a fixed snapshot.</p>
 <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh history</Button>
 {data.busy&&<LoadingState message="Loading commitment history…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data?.items.length===0&&<p>No history available yet.</p>}
 <ol className="history-list">{data.data?.items.map(event=><li key={event.id}><Card><h3>{event.actor.display_name}</h3><p>{historyText(event)}</p><time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
 {"repayment_id" in event.details&&<><StatusChip label={event.details.status==="PENDING_VERIFICATION"?"Pending verification":event.details.status==="VERIFIED"?"Verified":"Disputed"} status={event.details.status==="PENDING_VERIFICATION"?"PENDING":event.details.status==="VERIFIED"?"VERIFIED":"DISPUTED"}/>
 <Link className="button button--quiet" href={"/app/repayments/"+event.details.repayment_id}>View repayment</Link></>}
 {event.event_type==="REPAYMENT_VERIFIED"&&<p>Verified outstanding after this event: {formatMoney(event.details.resulting_verified_outstanding_minor,event.details.currency)}</p>}
 </Card></li>)}</ol>
 {data.data?.next_cursor&&<Button disabled={data.busy} onClick={()=>void data.loadMore()}>Load more history</Button>}</section>;
}
export function Activity(){
 const data=useCommitments();
 return <div className="commitments-feature"><h1>Activity</h1><p>Activity is recorded separately for each commitment.</p>
 <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh commitments</Button>
 {data.busy&&<LoadingState message="Loading your commitments…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data?.rows.length===0&&<><EmptyState title="No activity yet" message="Activity appears within your commitments as you and the other participant record changes."/><Link className="button button--primary" href="/app/commitments/new">Create commitment</Link></>}
 {data.data?.rows.map(row=><Card key={row.id} title={counterparty(row,data.userId)!.display_name}><p>{row.type==="IOU"?"IOU":"Peer loan"} · {formatMoney(row.principal_amount_minor,row.currency)}</p><StatusChip label={statusLabels[row.status]}/><Link className="button button--quiet" href={"/app/activity/"+row.id}>View history with {counterparty(row,data.userId)!.display_name}</Link></Card>)}</div>;
}
export function SelectedHistory({id}:{id:string}){
 const data=useCommitments(id),row=data.data?.detail;
 return <div className="commitments-feature"><Link className="auth-back" href="/app/activity">← Activity</Link><h1>Commitment history</h1>{data.busy&&<LoadingState message="Loading the commitment…"/>}{data.error&&<ErrorState message={data.error}/>}
 {row&&<><Card title={counterparty(row,data.userId)!.display_name}><p>{formatMoney(row.principal_amount_minor,row.currency)}</p><StatusChip label={statusLabels[row.status]}/><Link href={"/app/commitments/"+id}>View current commitment</Link></Card><History key={id} id={id}/></>}</div>;
}
