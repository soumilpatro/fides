"use client";
import Link from "next/link";
import { formatMoney } from "@fides/shared/domain/money";
import type { DueSummaryPage } from "@fides/shared/api/due-summaries";
import { dueDateLabel, dueInstallmentLabel, dueRoleLabel } from "@fides/shared/dashboard/due-presentation";
import { Button, Card, EmptyState, ErrorState, LoadingState } from "../../components/ui";
import { useDueSummaries } from "./useDueSummaries";

export interface DueSectionState { data:DueSummaryPage|null; busy:boolean; error:string|null }

function DueSection({title,state,onRetry,onLoadMore}:{title:string;state:DueSectionState;onRetry:()=>void;onLoadMore:()=>void}){
 return <section className="f6-stack" aria-label={title}><h2>{title}</h2>
  {state.busy&&!state.data&&<LoadingState message={"Loading "+title.toLowerCase()+"…"}/>}
  {state.error&&<><ErrorState message={state.error}/><Button variant="quiet" disabled={state.busy} onClick={onRetry}>Retry</Button></>}
  {state.data?.items.length===0&&<EmptyState title={"Nothing "+title.toLowerCase()} message={title.startsWith("Upcoming")?"No server-reported due items in the next 7 days.":"No server-reported overdue items."}/>}
  {state.data?.items.map(item=><Card key={(item.installment_id??item.commitment_id)+":"+item.due_date}>
   <h3>{item.counterparty.display_name}</h3><p>{dueRoleLabel(item)} · {dueInstallmentLabel(item)}</p>
   <strong className="amount amount--row">{formatMoney(item.verified_outstanding_minor,item.currency)}</strong>
   <p>Due {dueDateLabel(item.due_date)}</p>
   <p className="supporting">Due timezone: {item.due_timezone}</p>
   <Link className="button button--quiet" href={"/app/commitments/"+item.commitment_id}>View commitment</Link>
  </Card>)}
  {state.data?.next_cursor&&<Button variant="secondary" disabled={state.busy} onClick={onLoadMore}>Load more</Button>}
 </section>;
}

export function DueSummarySections(props:{upcoming:DueSectionState;overdue:DueSectionState;onRetryUpcoming:()=>void;onRetryOverdue:()=>void;onMoreUpcoming:()=>void;onMoreOverdue:()=>void}){
 return <><DueSection title="Upcoming — next 7 days" state={props.upcoming} onRetry={props.onRetryUpcoming} onLoadMore={props.onMoreUpcoming}/><DueSection title="Overdue" state={props.overdue} onRetry={props.onRetryOverdue} onLoadMore={props.onMoreOverdue}/></>;
}
export function DueSummaryOverview(){
 const data=useDueSummaries();
 return <DueSummarySections upcoming={data.upcoming} overdue={data.overdue} onRetryUpcoming={()=>void data.upcoming.refresh()} onRetryOverdue={()=>void data.overdue.refresh()} onMoreUpcoming={()=>void data.upcoming.loadMore()} onMoreOverdue={()=>void data.overdue.loadMore()}/>;
}
