import { View } from "react-native";
import type { DueSummaryPage } from "@fides/shared/api/due-summaries";
import { dueDateLabel, dueInstallmentLabel, dueRoleLabel } from "@fides/shared/dashboard/due-presentation";
import { Amount, Body, Button, Card, EmptyState, ErrorState, LoadingState, SectionTitle } from "../../components/ui";
import { useDueSummaries } from "./useDueSummaries";

export interface DueSectionState { data:DueSummaryPage|null; busy:boolean; error:string|null }

function DueSection({title,state,onRetry,onLoadMore,onOpen}:{title:string;state:DueSectionState;onRetry:()=>void;onLoadMore:()=>void;onOpen:(id:string)=>void}){
 const isUpcoming=title.startsWith("Upcoming"),sectionName=isUpcoming?"upcoming due items":"overdue items";
 return <><SectionTitle>{title}</SectionTitle>
  {state.data&&!state.error&&<Button title={"Refresh "+(isUpcoming?"upcoming":"overdue")} variant="quiet" disabled={state.busy} onPress={onRetry}/>}
  {state.busy&&!state.data&&<LoadingState message={"Loading "+sectionName+"…"}/>}
  {state.busy&&state.data&&<View accessibilityLiveRegion="polite"><Body supporting>Updating {sectionName}…</Body></View>}
  {state.error&&<><ErrorState message={state.error}/><Button title={"Retry "+(isUpcoming?"upcoming":"overdue")} variant="quiet" disabled={state.busy} onPress={onRetry}/></>}
  {state.data?.items.length===0&&<EmptyState title={isUpcoming?"Nothing upcoming":"Nothing overdue"} message={isUpcoming?"No server-reported due items in the next 7 days.":"No server-reported overdue items."}/>}
  {state.data?.items.map(item=><Card key={(item.installment_id??item.commitment_id)+":"+item.due_date} title={item.counterparty.display_name}>
   <Body>{dueRoleLabel(item)} · {dueInstallmentLabel(item)}</Body><Body supporting>Verified outstanding</Body><Amount minor={item.verified_outstanding_minor} currency={item.currency} size="row"/><Body>Due {dueDateLabel(item.due_date)}</Body><Body supporting>Due timezone: {item.due_timezone}</Body>
   <Button title={"View commitment with "+item.counterparty.display_name} variant="quiet" onPress={()=>onOpen(item.commitment_id)}/>
  </Card>)}
  {state.data?.next_cursor&&<Button title={"Load more "+(isUpcoming?"upcoming":"overdue")} variant="secondary" disabled={state.busy} onPress={onLoadMore}/>}
 </>;
}

export function DueSummarySections(props:{upcoming:DueSectionState;overdue:DueSectionState;onRetryUpcoming:()=>void;onRetryOverdue:()=>void;onMoreUpcoming:()=>void;onMoreOverdue:()=>void;onOpen:(id:string)=>void}){
 return <><DueSection title="Upcoming — next 7 days" state={props.upcoming} onRetry={props.onRetryUpcoming} onLoadMore={props.onMoreUpcoming} onOpen={props.onOpen}/><DueSection title="Overdue" state={props.overdue} onRetry={props.onRetryOverdue} onLoadMore={props.onMoreOverdue} onOpen={props.onOpen}/></>;
}
export function DueSummaryOverview({onOpen}:{onOpen:(id:string)=>void}){
 const data=useDueSummaries();
 return <DueSummarySections upcoming={data.upcoming} overdue={data.overdue} onRetryUpcoming={()=>void data.upcoming.refresh()} onRetryOverdue={()=>void data.overdue.refresh()} onMoreUpcoming={()=>void data.upcoming.loadMore()} onMoreOverdue={()=>void data.overdue.loadMore()} onOpen={onOpen}/>;
}
