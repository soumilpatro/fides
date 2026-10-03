"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { MutualClosure, MutualClosureRequestBody } from "@fides/shared/api/mutual-closure";
import type { Commitment } from "@fides/shared/api/commitments";
import type { Repayment } from "@fides/shared/api/repayments";
import { canRequestMutualClosure, mutualClosureActions } from "@fides/shared/mutual-closure/model";
import { useAuth } from "../auth/useAuth";

interface Snapshot { rows:MutualClosure[];parent:Commitment;repayments:Repayment[] }

export function useMutualClosure(id:string){
  const {mutualClosure,commitments,repayments,intents,session,state}=useAuth(),user=state.status==="authenticated"?state.user.id:"";
  const [data,setData]=useState<Snapshot|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState<string|null>(null);
  const live=useRef(false),flight=useRef(false),generation=useRef(0),snapshot=useRef<Snapshot|null>(null);
  const scope=useCallback((action:string,resource=id)=>user+":mutual-closure:"+resource+":"+action,[user,id]);

  const read=useCallback(async()=>{
    const get=()=>Promise.all([mutualClosure.listClosureRequests(id),commitments.getCommitment(id),repayments.listRepayments(id)]);
    let result:Awaited<ReturnType<typeof get>>;
    try{result=await get();}catch(e){if(!(e instanceof ApiError)||e.status!==401)throw e;await session.bootstrap();if(session.snapshot().status!=="authenticated")throw e;result=await get();}
    const [rows,parent,reports]=result,participants=[parent.borrower.id,parent.lender.id];
    if(parent.id!==id||!participants.includes(user)||rows.some(row=>row.commitment_id!==id||!participants.includes(row.requested_by.id)||!participants.includes(row.counterparty.id))||reports.some(row=>row.commitment_id!==id))throw new Error("Unavailable record.");
    return {rows,parent,repayments:reports};
  },[mutualClosure,commitments,repayments,id,session,user]);

  const reconcile=useCallback((next:Snapshot)=>{
    const createKey=scope("create"),pendingCreate=intents.get(createKey);
    if(pendingCreate){
      const body=JSON.parse(pendingCreate.payload) as MutualClosureRequestBody;
      const confirmed=next.rows.some(row=>row.status==="REQUESTED"&&row.requested_by.id===user&&row.note===body.note);
      if(confirmed)intents.succeeded(createKey);
      else{
        if(next.rows.some(row=>row.status==="REQUESTED"))pendingCreate.blocked=true;
        intents.reconciled(createKey);
      }
    }
    for(const row of next.rows)for(const action of ["accept","reject","cancel"] as const){
      const key=scope(action,row.id);if(!intents.get(key))continue;
      if(row.status!=="REQUESTED")intents.succeeded(key);else intents.reconciled(key);
    }
  },[intents,scope]);

  const refresh=useCallback(async()=>{
    if(flight.current||!user)return;flight.current=true;const version=++generation.current;setBusy(true);setError(null);
    try{const next=await read();if(live.current&&generation.current===version){reconcile(next);snapshot.current=next;setData(next);}}
    catch(e){if(live.current&&generation.current===version)setError(e instanceof ApiError?e.message:"Mutual closure is unavailable. Refresh to try again.");}
    finally{if(generation.current===version){flight.current=false;if(live.current)setBusy(false);}}
  },[read,reconcile,user]);

  useEffect(()=>{live.current=true;flight.current=false;let active=true;queueMicrotask(()=>{if(active)void refresh();});return()=>{active=false;live.current=false;generation.current++;};},[refresh]);

  const pending=(action:string,resource=id)=>intents.get(scope(action,resource));

  const mutate=async(action:"create"|"accept"|"reject"|"cancel",body:MutualClosureRequestBody|Record<string,never>,row?:MutualClosure)=>{
    const current=snapshot.current;if(flight.current||!current)return null;
    const resource=row?.id??id,keyScope=scope(action,resource);
    if(action==="create"&&!pending("create")&&!canRequestMutualClosure(current.parent,current.rows))return null;
    if(row&&!pending(action,resource)&&!mutualClosureActions(row,user).includes(action as "accept"|"reject"|"cancel"))return null;
    const otherActions=["accept","reject","cancel"].filter(other=>other!==action);
    if(row&&otherActions.some(other=>!!pending(other,row.id))&&!pending(action,row.id)){setError("Resolve the earlier mutual-closure action before changing it.");return null;}
    let intent;try{intent=intents.begin(keyScope,body);}catch(e){setError(e instanceof Error?e.message:"Refresh before retrying.");return null;}
    flight.current=true;const version=++generation.current;setBusy(true);setError(null);let result:MutualClosure|null=null,message:string|null=null;
    try{
      result=action==="create"?await mutualClosure.requestClosure(id,body as MutualClosureRequestBody,intent.key):
        action==="accept"?await mutualClosure.acceptClosure(resource,id,intent.key):
        action==="reject"?await mutualClosure.rejectClosure(resource,id,intent.key):
        await mutualClosure.cancelClosure(resource,id,intent.key);
      intents.succeeded(keyScope);
    }catch(e){
      intents.failed(keyScope,e);
      message=e instanceof ApiError&&action==="accept"&&e.code==="CONFLICT"
        ?"This request can't be accepted yet. A repayment may still be pending verification or the verified outstanding balance changed. Refresh after resolving the record."
        :e instanceof ApiError?e.message:"The outcome is uncertain. Refresh before explicitly retrying the same action.";
      if(e instanceof ApiError&&e.status===401)await session.bootstrap();
    }
    try{const next=await read();if(live.current&&generation.current===version){reconcile(next);snapshot.current=next;setData(next);}}
    catch{if(live.current&&generation.current===version){snapshot.current=null;setData(null);message=message??"The action returned, but the current record could not be reloaded. Refresh before continuing.";}}
    finally{if(generation.current===version){flight.current=false;if(live.current){setBusy(false);setError(message);}}}
    return live.current?result:null;
  };

  return {data,busy,error,user,refresh,pending,request:(body:MutualClosureRequestBody)=>mutate("create",body),decide:(row:MutualClosure,action:"accept"|"reject"|"cancel")=>mutate(action,{},row)};
}
