import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import { appendDueSummary, type DueSummariesApi, type DueSummaryKind, type DueSummaryPage } from "@fides/shared/api/due-summaries";
import { useAuth } from "../auth/useAuth";

export interface DueSectionState { data:DueSummaryPage|null; busy:boolean; error:string|null }

function useDueSection(api:DueSummariesApi,session:ReturnType<typeof useAuth>["session"],user:string,kind:DueSummaryKind){
 const [data,setData]=useState<DueSummaryPage|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState<string|null>(null);
 const mounted=useRef(false),flight=useRef(false),generation=useRef(0),snapshot=useRef<DueSummaryPage|null>(null);

 const read=useCallback(async(options:{limit?:number;cursor?:string}={})=>{
  try{return await api.list(kind,options);}catch(e){
   if(!(e instanceof ApiError)||e.status!==401)throw e;
   await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;
   return api.list(kind,options);
  }
 },[api,kind,session]);

 const refresh=useCallback(async()=>{
  if(flight.current||!user)return;flight.current=true;const version=++generation.current;setBusy(true);setError(null);
  try{const next=await read({limit:50});if(mounted.current&&version===generation.current){snapshot.current=next;setData(next);}}
  catch(e){if(mounted.current&&version===generation.current)setError(e instanceof ApiError?e.message:"Due-date summary unavailable. Retry to continue.");}
  finally{if(version===generation.current){flight.current=false;if(mounted.current)setBusy(false);}}
 },[read,user]);

 const loadMore=useCallback(async()=>{
  const current=snapshot.current;if(flight.current||!current?.next_cursor)return;
  flight.current=true;const version=++generation.current;setBusy(true);setError(null);
  try{
   const page=await read({limit:50,cursor:current.next_cursor});
   if(mounted.current&&version===generation.current){
    const next={items:appendDueSummary(current.items,page.items),next_cursor:page.next_cursor};
    snapshot.current=next;setData(next);
   }
  }catch(e){if(mounted.current&&version===generation.current)setError(e instanceof ApiError?e.message:"More due-date items could not be loaded. Retry to continue.");}
  finally{if(version===generation.current){flight.current=false;if(mounted.current)setBusy(false);}}
 },[read]);

 useEffect(()=>{mounted.current=true;flight.current=false;let active=true;queueMicrotask(()=>{if(active)void refresh();});return()=>{active=false;mounted.current=false;generation.current++;};},[refresh]);
 return {data,busy,error,refresh,loadMore};
}

export function useDueSummaries(){
 const {dueSummaries,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
 const upcoming=useDueSection(dueSummaries,session,user,"upcoming");
 const overdue=useDueSection(dueSummaries,session,user,"overdue");
 return {upcoming,overdue};
}
