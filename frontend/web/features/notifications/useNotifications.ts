"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { Notification, NotificationPage } from "@fides/shared/api/notifications";
import { appendNotifications } from "@fides/shared/notifications/presentation";
import { useAuth } from "../auth/useAuth";
export function useNotifications(){
 const {notifications,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
 const [data,setData]=useState<NotificationPage|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState<string|null>(null);
 const snapshot=useRef<NotificationPage|null>(null),live=useRef(false),generation=useRef(0),flight=useRef(false),reading=useRef(new Set<string>());
 const load=useCallback(async(reset:boolean)=>{
  if(flight.current||!user)return;const previous=reset?null:snapshot.current;if(!reset&&!previous?.next_cursor)return;
  flight.current=true;const version=++generation.current;setBusy(true);setError(null);if(reset){snapshot.current=null;setData(null);}
  try{const get=()=>notifications.listNotifications({limit:50,...(previous?.next_cursor?{cursor:previous.next_cursor}:{})});let page;
   try{page=await get();}catch(e){if(!(e instanceof ApiError)||e.status!==401)throw e;await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;page=await get();}
   if(live.current&&version===generation.current){const next={items:appendNotifications(previous?.items??[],page.items),next_cursor:page.next_cursor};snapshot.current=next;setData(next);}
  }catch{if(live.current&&version===generation.current)setError("Notifications unavailable. Refresh or retry Load more.");}
  finally{if(version===generation.current){flight.current=false;if(live.current)setBusy(false);}}
 },[notifications,session,user]);
 useEffect(()=>{live.current=true;flight.current=false;let active=true;queueMicrotask(()=>{if(active)void load(true);});const counter=generation;return()=>{active=false;live.current=false;counter.current++;};},[load]);
 const activate=async(row:Notification)=>{
  if(row.read_at||reading.current.has(row.id))return;reading.current.add(row.id);const version=generation.current;
  try{const result=await notifications.markRead(row.id);
   if(result.commitment_id!==row.commitment_id||result.type!==row.type||result.repayment_id!==row.repayment_id||result.extension_request_id!==row.extension_request_id)throw new Error("Invalid response.");
   if(live.current&&version===generation.current&&snapshot.current){const next={...snapshot.current,items:snapshot.current.items.map(r=>r.id===result.id?result:r)};snapshot.current=next;setData(next);}
  }catch{if(live.current)setError("The notification could not be marked read. You can still open its record.");}
  finally{reading.current.delete(row.id);}
 };
 return {data,busy,error,activate,refresh:()=>load(true),loadMore:()=>load(false)};
}
