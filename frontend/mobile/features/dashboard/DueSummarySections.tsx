import { formatMoney } from "@fides/shared/domain/money";
import type { DueSummaryPage } from "@fides/shared/api/due-summaries";
import { dueDateLabel, dueInstallmentLabel, dueRoleLabel } from "@fides/shared/dashboard/due-presentation";
import { Body, Button, Card, EmptyState, ErrorState, LoadingState, Title } from "../../components/ui";

export interface DueSectionState { data:DueSummaryPage|null; busy:boolean; error:string|null }

function DueSection({title,state,onRetry,onLoadMore,onOpen}:{title:string;state:DueSectionState;onRetry:()=>void;onLoadMore:()=>void;onOpen:(id:string)=>void}){
 return <><Title>{title}</Title>
  {state.busy&&!state.data&&<LoadingState message={"Loading "+title.toLowerCase()+"…"}/>}
  {state.error&&<><ErrorState message={state.error}/><Button title="Retry" variant="quiet" disabled={state.busy} onPress={onRetry}/></>}
  {state.data?.items.length===0&&<EmptyState title={"Nothing "+title.toLowerCase()} message={title.startsWith("Upcoming")?"No server-reported due items in the next 7 days.":"No server-reported overdue items."}/>}
  {state.data?.items.map(item=><Card key={(item.installment_id??item.commitment_id)+":"+item.due_date} title={item.counterparty.display_name}>
   <Body>{dueRoleLabel(item)} · {dueInstallmentLabel(item)}</Body><Body>{formatMoney(item.verified_outstanding_minor,item.currency)}</Body><Body>Due {dueDateLabel(item.due_date)}</Body><Body supporting>Due timezone: {item.due_timezone}</Body>
   <Button title="View commitment" variant="quiet" onPress={()=>onOpen(item.commitment_id)}/>
  </Card>)}
  {state.data?.next_cursor&&<Button title="Load more" variant="secondary" disabled={state.busy} onPress={onLoadMore}/>}
 </>;
}

export function DueSummarySections(props:{upcoming:DueSectionState;overdue:DueSectionState;onRetryUpcoming:()=>void;onRetryOverdue:()=>void;onMoreUpcoming:()=>void;onMoreOverdue:()=>void;onOpen:(id:string)=>void}){
 return <><DueSection title="Upcoming — next 7 days" state={props.upcoming} onRetry={props.onRetryUpcoming} onLoadMore={props.onMoreUpcoming} onOpen={props.onOpen}/><DueSection title="Overdue" state={props.overdue} onRetry={props.onRetryOverdue} onLoadMore={props.onMoreOverdue} onOpen={props.onOpen}/></>;
}
// Prepared only. Do not mount until the corresponding backend endpoints are merged.
