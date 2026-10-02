"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { SummaryResponse } from "@fides/shared/api/dashboard";
import { useAuth } from "../auth/useAuth";
export function useDashboard(){
 const {dashboard,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
 const [data,setData]=useState<SummaryResponse|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState<string|null>(null);
 const generation=useRef(0),mounted=useRef(false),flight=useRef(false);
 const refresh=useCallback(async()=>{
  if(flight.current||!user)return;flight.current=true;const version=++generation.current;
  setBusy(true);setData(null);setError(null);
  try{
   let result:SummaryResponse;
   try{result=await dashboard.getSummary();}catch(e){
    if(!(e instanceof ApiError)||e.status!==401)throw e;
    await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;
    result=await dashboard.getSummary();
   }
   if(mounted.current&&version===generation.current)setData(result);
  }catch{if(mounted.current&&version===generation.current)setError("Summary unavailable. Refresh to try again.");}
  finally{if(version===generation.current){flight.current=false;if(mounted.current)setBusy(false);}}
 },[dashboard,session,user]);
 useEffect(()=>{mounted.current=true;flight.current=false;const counter=generation;let active=true;queueMicrotask(()=>{if(active)void refresh();});return()=>{active=false;mounted.current=false;counter.current++;};},[refresh]);
 return {data,busy,error,refresh};
}
