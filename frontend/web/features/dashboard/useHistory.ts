"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { LedgerResponse } from "@fides/shared/api/ledger";
import { appendHistory } from "@fides/shared/dashboard/presentation";
import { useAuth } from "../auth/useAuth";
export function useHistory(id:string){
 const {ledger,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
 const [data,setData]=useState<LedgerResponse|null>(null),[error,setError]=useState<string|null>(null),[busy,setBusy]=useState(true);
 const snapshot=useRef<LedgerResponse|null>(null),generation=useRef(0),mounted=useRef(false),flight=useRef(false);
 const load=useCallback(async(reset:boolean)=>{
  if(flight.current||!user)return;
  const previous=reset?null:snapshot.current;if(!reset&&!previous?.next_cursor)return;
  flight.current=true;const version=++generation.current;setBusy(true);setError(null);
  if(reset){snapshot.current=null;setData(null);}
  const options={limit:50,...(previous?.next_cursor?{cursor:previous.next_cursor}:{})};
  try{
   const get=()=>ledger.getCommitmentLedger(id,options);let result:LedgerResponse;
   try{result=await get();}catch(e){
    if(!(e instanceof ApiError)||e.status!==401)throw e;
    await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;result=await get();
   }
   if(mounted.current&&version===generation.current){
    const next={items:appendHistory(previous?.items??[],result.items),next_cursor:result.next_cursor};
    snapshot.current=next;setData(next);
   }
  }catch(e){if(mounted.current&&version===generation.current)setError(e instanceof ApiError&&e.status===404?"Unavailable resource.":reset?"History unavailable. Refresh to try again.":"Additional history unavailable. Retry Load more history.");}
  finally{if(version===generation.current){flight.current=false;if(mounted.current)setBusy(false);}}
 },[id,ledger,session,user]);
 useEffect(()=>{mounted.current=true;flight.current=false;snapshot.current=null;const counter=generation;let active=true;queueMicrotask(()=>{if(active)void load(true);});return()=>{active=false;mounted.current=false;counter.current++;};},[load]);
 return {data,error,busy,refresh:()=>load(true),loadMore:()=>load(false)};
}
