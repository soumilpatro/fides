"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { Extension, ExtensionRequest } from "@fides/shared/api/extensions";
import type { Commitment, Terms } from "@fides/shared/api/commitments";
import { canRequestExtension, extensionActions, staleExtension } from "@fides/shared/extensions/model";
import { currentTerms } from "@fides/shared/commitments/model";
import { useAuth } from "../auth/useAuth";
interface Snapshot { rows:Extension[];parent:Commitment;terms:Terms }
export function useExtensions(id:string){
 const {extensions,commitments,intents,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
 const [data,setData]=useState<Snapshot|null>(null),[error,setError]=useState<string|null>(null),[busy,setBusy]=useState(true);
 const live=useRef(false),generation=useRef(0),flight=useRef(false),snapshot=useRef<Snapshot|null>(null);
 const scope=useCallback((action:string,resource=id)=>user+":extension:"+resource+":"+action,[user,id]);
 const read=useCallback(async()=>{
  const get=()=>Promise.all([extensions.listExtensions(id),commitments.getCommitment(id),commitments.getCommitmentTerms(id)]);
  let result:Awaited<ReturnType<typeof get>>;
  try{result=await get();}catch(e){if(!(e instanceof ApiError)||e.status!==401)throw e;await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;result=await get();}
  const [rows,parent,terms]=result,people=[parent.borrower.id,parent.lender.id];
  if(parent.id!==id||!people.includes(user)||rows.some(r=>r.commitment_id!==id||!people.includes(r.requested_by.id)||r.decided_by&&!people.includes(r.decided_by.id)))throw new Error("Unavailable record.");
  return {rows,parent,terms};
 },[extensions,commitments,id,session,user]);
 const reconcile=useCallback((next:Snapshot)=>{
  const creation=scope("create"),pending=intents.get(creation);
  if(pending){const body=JSON.parse(pending.payload) as ExtensionRequest;
   // Equal values alone do not prove which request succeeded. Retain its key for explicit replay.
   if(next.rows.some(r=>r.status==="REQUESTED"&&r.requested_by.id!==user))pending.blocked=true;
   if(!canRequestExtension(next.parent,next.terms,next.rows)&&!next.rows.some(r=>r.requested_by.id===user&&r.requested_due_date===body.requested_due_date&&r.reason===body.reason))pending.blocked=true;
   intents.reconciled(creation);
  }
  for(const row of next.rows)for(const action of ["accept","reject"]){
   const key=scope(action,row.id);if(!intents.get(key))continue;
   if(row.status!=="REQUESTED")intents.succeeded(key);else intents.reconciled(key);
  }
 },[intents,scope,user]);
 const refresh=useCallback(async()=>{
  if(flight.current||!user)return;flight.current=true;const version=++generation.current;setBusy(true);setError(null);setData(null);snapshot.current=null;
  try{const next=await read();if(live.current&&generation.current===version){reconcile(next);snapshot.current=next;setData(next);}}
  catch(e){if(live.current&&generation.current===version)setError(e instanceof ApiError&&e.status===404?"Unavailable resource.":"Extensions unavailable. Refresh to try again.");}
  finally{if(generation.current===version){flight.current=false;if(live.current)setBusy(false);}}
 },[read,reconcile,user]);
 useEffect(()=>{live.current=true;flight.current=false;let active=true;queueMicrotask(()=>{if(active)void refresh();});const counter=generation;return()=>{active=false;live.current=false;counter.current++;};},[refresh]);
 const pending=(action:string,resource=id)=>intents.get(scope(action,resource));
 const mutate=async(action:"create"|"accept"|"reject",body:ExtensionRequest|Record<string,never>,row?:Extension)=>{
  const previous=snapshot.current;if(flight.current||!previous)return null;
  const resource=row?.id??id,k=scope(action,resource);
  if(action!=="create"&&(pending("accept",resource)||pending("reject",resource))&&!pending(action,resource)){setError("Resolve the earlier decision before changing action.");return null;}
  if(action==="create"&&!pending(action)&&!canRequestExtension(previous.parent,previous.terms,previous.rows))return null;
  if(row&&!pending(action,resource)&&!extensionActions(row,user,previous.parent,previous.terms).includes(action as "accept"|"reject"))return null;
  let intent;try{intent=intents.begin(k,body);}catch(e){setError(e instanceof Error?e.message:"Refresh before retrying.");return null;}
  flight.current=true;const version=++generation.current;setBusy(true);setError(null);
  let result:Extension|null=null,message:string|null=null;
  try{result=action==="create"?await extensions.requestExtension(id,body as ExtensionRequest,intent.key):action==="accept"?await extensions.acceptExtension(resource,id,intent.key):await extensions.rejectExtension(resource,id,intent.key);intents.succeeded(k);}
  catch(e){if(e instanceof ApiError&&e.status===409&&e.code==="CONFLICT")intents.succeeded(k);else intents.failed(k,e);message=e instanceof ApiError&&action==="accept"&&e.code==="CONFLICT"?staleExtension:e instanceof ApiError?e.message:"The outcome is uncertain. Refresh before explicitly retrying the same request.";if(e instanceof ApiError&&e.status===401)await session.bootstrap();}
  // Always re-read current terms/parent/list. No optimistic due date or new version.
  try{const next=await read();if(live.current&&version===generation.current){reconcile(next);snapshot.current=next;setData(next);}}
  catch{if(live.current&&version===generation.current){snapshot.current=null;setData(null);message=message??"Saved response received; refresh current terms before continuing.";}}
  finally{if(version===generation.current){flight.current=false;if(live.current){setError(message);setBusy(false);}}}
  return live.current?result:null;
 };
 return {data,error,busy,user,refresh,pending,request:(body:ExtensionRequest)=>mutate("create",body),decide:(row:Extension,action:"accept"|"reject")=>mutate(action,{},row),
  due:data?currentTerms(data.terms).due_date:null};
}
