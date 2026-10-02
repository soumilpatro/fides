import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { Commitment } from "@fides/shared/api/commitments";
import type { Repayment, Verification, RepaymentRequest, DecisionRequest } from "@fides/shared/api/repayments";
import { commitmentRole } from "@fides/shared/commitments/model";
import { belongs, canReport, canDecide, coherentHistory, repaymentError, type DecisionAction } from "@fides/shared/repayments/model";
import { useAuth } from "../auth/useAuth";
interface Snapshot { parent: Commitment; rows: Repayment[]; detail: Repayment | null; history: Verification[] | null }
export function useRepayments(parentId?: string, repaymentId?: string) {
  const { state, session, commitments, repayments, intents } = useAuth();
  const userId = state.status === "authenticated" ? state.user.id : "";
  const [data,setData] = useState<Snapshot | null>(null), [error,setError] = useState<string | null>(null);
  const [busy,setBusy] = useState(true), [fresh,setFresh] = useState(false), [revision,setRevision] = useState(0);
  const mounted=useRef(false), flight=useRef(false), generation=useRef(0);
  const scope=useCallback((action: "report" | DecisionAction) => userId+":f4:"+(action === "report" ? parentId : repaymentId)+":"+action,[parentId,repaymentId,userId]);
  const read=useCallback(async <T,>(get:()=>Promise<T>) => {
    try { return await get(); } catch(failure) {
      if (!(failure instanceof ApiError) || failure.status !== 401) throw failure;
      await session.bootstrap(); if (session.snapshot().status !== "authenticated") throw failure; return get();
    }
  },[session]);
  const reconcile=useCallback(async () => {
    const version=++generation.current;
    const detail=repaymentId ? await read(()=>repayments.getRepayment(repaymentId)) : null;
    if (detail && detail.id !== repaymentId) throw new ApiError("INVALID_RESPONSE","Unavailable resource.",null);
    const identifier=detail?.commitment_id ?? parentId;
    if (!identifier) throw new ApiError("NOT_FOUND","Unavailable resource.",404);
    const [parent,rows,history]=await Promise.all([read(()=>commitments.getCommitment(identifier)),read(()=>repayments.listRepayments(identifier)),detail ? read(()=>repayments.getVerificationHistory(detail.id)) : null]);
    if (parent.id !== identifier || !commitmentRole(parent,userId)) throw new ApiError("NOT_FOUND","Unavailable resource.",404);
    if (rows.some(row=>!belongs(row,parent)) || new Set(rows.map(row=>row.id)).size !== rows.length || (detail && (!history || !coherentHistory(detail,parent,history))))
      throw new ApiError("INVALID_RESPONSE","Records changed. Refresh the record and history.",null);
    if (mounted.current && version === generation.current) {
      setData({parent,rows,detail,history});setFresh(true);
      intents.reconciled(scope("report"));
      for(const action of ["verify","dispute"] as const) {
        if (detail && detail.status !== "PENDING_VERIFICATION") intents.succeeded(scope(action)); else intents.reconciled(scope(action));
      }
      setRevision(v=>v+1);
    }
  },[commitments,repayments,parentId,repaymentId,read,userId,intents,scope]);
  const failedRead=(failure:unknown) => { if(mounted.current){setFresh(false);setError(repaymentError(failure));if(failure instanceof ApiError && failure.status===404)setData(null);} };
  const refresh=useCallback(async () => {
    if(flight.current)return;flight.current=true;setBusy(true);setFresh(false);setError(null);
    try{await reconcile();}catch(failure){if(mounted.current){setError(repaymentError(failure));if(failure instanceof ApiError && failure.status===404)setData(null);}}
    finally{flight.current=false;if(mounted.current)setBusy(false);}
  },[reconcile]);
  useEffect(()=>{mounted.current=true;flight.current=true;const versionRef=generation;let cancelled=false;
    void reconcile().catch(failure=>{if(!cancelled)setError(repaymentError(failure));}).finally(()=>{if(!cancelled){flight.current=false;setBusy(false);}});
    return()=>{cancelled=true;mounted.current=false;versionRef.current++;};
  },[reconcile]);
  const actionBlocked=(action:DecisionAction)=>!!intents.get(scope(action === "verify" ? "dispute" : "verify"));
  const mutate=async (action:"report"|DecisionAction,body:RepaymentRequest|DecisionRequest) => {
    if(flight.current || !fresh || !data || (action === "report" ? !canReport(data.parent,userId) : !data.detail || !canDecide(data.detail,data.parent,userId) || actionBlocked(action)))return null;
    const operation=scope(action);let intent;
    try{intent=intents.begin(operation,body);}catch{setError("Resolve the pending request before changing or retrying it.");return null;}
    flight.current=true;setBusy(true);setFresh(false);setError(null);
    try{
      const row=action === "report" ? await repayments.reportRepayment(data.parent.id,body as RepaymentRequest,intent.key) :
        await (action === "verify" ? repayments.verifyRepayment : repayments.disputeRepayment)(repaymentId!,body as DecisionRequest,intent.key);
      if(row.status !== (action === "report" ? "PENDING_VERIFICATION" : action === "verify" ? "VERIFIED" : "DISPUTED") || !belongs(row,data.parent) || (action !== "report" && row.id !== repaymentId) || (action === "report" && row.reported_by.id !== userId))throw new ApiError("INVALID_RESPONSE","Unavailable resource.",null);
      intents.succeeded(operation);
      if(mounted.current && repaymentId)setData(previous=>previous ? {...previous,detail:row,history:null} : null);
      try{await reconcile();}catch(failure){failedRead(failure);if(mounted.current)setError("Request completed. Refresh to load the current commitment, repayment and history.");}
      return mounted.current ? row : null;
    }catch(failure){
      intents.failed(operation,failure);if(mounted.current)setError(repaymentError(failure));
      if(failure instanceof ApiError && failure.status===401)await session.bootstrap();
      if(session.snapshot().status === "authenticated")try{await reconcile();}catch(error){failedRead(error);}
      return null;
    }finally{flight.current=false;if(mounted.current){setBusy(false);setRevision(v=>v+1);}}
  };
  void revision;
  return {data,error,busy,fresh,userId,refresh,actionBlocked,pending:(action:"report"|DecisionAction)=>intents.get(scope(action)),
    report:(body:RepaymentRequest)=>mutate("report",body),decide:(action:DecisionAction,body:DecisionRequest)=>mutate(action,body)};
}
