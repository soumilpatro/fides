"use client";
import { useEffect, useRef, useState } from "react";
import { formatMoney } from "@fides/shared/domain/money";
import { closureBody, type MutualClosure } from "@fides/shared/api/mutual-closure";
import { canRequestMutualClosure, closureStatusLabel, hasPendingRepayment, mutualClosureActions, verifiedRepayments } from "@fides/shared/mutual-closure/model";
import { Button, Card, EmptyState, ErrorState, LoadingState, StatusChip } from "../../components/ui";
import { trapConfirmationFocus } from "../f6-dialog";
import { useMutualClosure } from "./useMutualClosure";
import { dateOnlyLabel } from "@fides/shared/dashboard/due-presentation";
import { useAuth } from "../auth/useAuth";
import { notificationTimestamp as formatTimestamp } from "@fides/shared/notifications/presentation";

function Confirmation({row,action,onCancel,onConfirm}:{row:MutualClosure;action:"accept"|"reject"|"cancel";onCancel:()=>void;onConfirm:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>previous?.focus();},[]);
 const title=action==="accept"?"Accept mutual closure?":action==="reject"?"Reject mutual closure?":"Cancel mutual closure request?";
 const body=action==="accept"
  ?"The commitment will close by mutual agreement and the remaining verified balance shown here will be waived. This is not a repayment."
  :action==="reject"?"The commitment will remain open. No balance will be waived.":"The pending request will be cancelled. The commitment will remain open.";
 return <dialog tabIndex={-1} onKeyDown={trapConfirmationFocus} className="connection-confirm f6-dialog" ref={dialog} aria-labelledby="closure-confirm-title" aria-describedby="closure-confirm-body" onCancel={onCancel}>
  <h2 id="closure-confirm-title">{title}</h2><p id="closure-confirm-body">{body}</p>
  <div className="button-row"><Button variant="quiet" autoFocus onClick={onCancel}>Go back</Button><Button variant={action==="accept"?"primary":"secondary"} onClick={onConfirm}>{action==="accept"?"Accept mutual closure":action==="reject"?"Reject request":"Cancel request"}</Button></div>
 </dialog>;
}

export function MutualClosureSection({id,onChanged}:{id:string;onChanged:()=>void}){
 const data=useMutualClosure(id),[requesting,setRequesting]=useState(false),[note,setNote]=useState(""),[validation,setValidation]=useState<string|null>(null),[confirmation,setConfirmation]=useState<{row:MutualClosure;action:"accept"|"reject"|"cancel"}|null>(null);
 const snapshot=data.data,verified=snapshot?verifiedRepayments(snapshot.repayments):[],pendingVerification=snapshot?hasPendingRepayment(snapshot.repayments):false;
 const createPending=data.pending("create");
 const {state}=useAuth();
 if(state.status!=="authenticated")return null;
 return <section id="mutual-closure" className="f6-stack" aria-labelledby="mutual-closure-title">
  <h2 id="mutual-closure-title">Mutual closure</h2>
  <p className="supporting">Mutual closure is not repayment or unilateral forgiveness. Both people must agree before the commitment can close.</p>
  <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh mutual closure</Button>
  {data.busy&&!snapshot&&<LoadingState message="Loading mutual-closure status…"/>}{data.error&&<ErrorState message={data.error}/>}
  {snapshot&&<>
   <Card title="Verified repayments">
    {verified.length===0?<p>No verified repayments recorded.</p>:<ul className="history-list">{verified.map(row=><li key={row.id}><span className="amount amount--row">{formatMoney(row.amount_minor,row.currency)}</span><span> · {dateOnlyLabel(row.payment_date)} · reported by {row.reported_by.display_name}</span></li>)}</ul>}
    <p className="supporting">Only verified repayments are shown here. Fides does not turn a waiver into a repayment entry.</p>
   </Card>
   {canRequestMutualClosure(snapshot.parent,snapshot.rows)&&!requesting&&!createPending&&<Button onClick={()=>{setNote("");setValidation(null);setRequesting(true);}}>Request mutual closure</Button>}
   {createPending&&!requesting&&<Button variant="secondary" onClick={()=>setRequesting(true)}>Review earlier mutual-closure request</Button>}
   {requesting&&<Card title="Request mutual closure">
    <p>Both you and the other person must agree. The remaining verified balance will be waived.</p>
    <p className="supporting">The server will record the authoritative verified outstanding amount when this request is created.</p>
    <label className="field">Note (optional)<textarea maxLength={500} value={note} disabled={data.busy} onChange={e=>{setNote(e.target.value);setValidation(null);}} aria-describedby="closure-note-count"/></label>
    <small id="closure-note-count">{Array.from(note.trim()).length}/500 characters after trimming</small>
    {validation&&<ErrorState message={validation}/>}
    <div className="button-row"><Button variant="quiet" disabled={data.busy} onClick={()=>setRequesting(false)}>Go back</Button><Button disabled={data.busy||!!createPending?.blocked||!!createPending?.needsReconcile} onClick={()=>{try{const body=createPending?JSON.parse(createPending.payload):closureBody(note);setValidation(null);void data.request(body).then(result=>{if(result){setRequesting(false);onChanged();}});}catch(e){setValidation(e instanceof Error?e.message:"Check the note.");}}}>{createPending?"Retry same request":"Send request"}</Button></div>
    {createPending&&<p role="status">An earlier attempt may have completed. Refresh before explicitly retrying; the same idempotency key and payload are retained.</p>}
   </Card>}
   {!snapshot.rows.length&&!requesting&&<EmptyState title="No mutual-closure requests" message="When eligible, either participant can request closure by mutual agreement."/>}
   {snapshot.rows.map(row=><Card key={row.id}>
    <StatusChip label={closureStatusLabel(row,data.user)} status={row.status==="REQUESTED"?"PENDING":row.status==="ACCEPTED"?"CLOSED":undefined}/>
    <p>Requested by {row.requested_by.display_name}</p>
    <dl className="commitment-facts"><dt>{row.status==="ACCEPTED"?"Verified outstanding at closure":"Verified outstanding reviewed"}</dt><dd className="amount">{formatMoney(row.outstanding_snapshot_minor,row.currency)}</dd>
    <dt>{row.status==="ACCEPTED"?"Waived amount":"Amount proposed to be waived"}</dt><dd className="amount">{formatMoney(row.waived_amount_minor,row.currency)}</dd></dl>
    {row.note&&<p className="f6-wrap">{row.note}</p>}
    {row.decided_by&&<p>{row.decided_by.display_name} · <time dateTime={row.decided_at!}>{formatTimestamp(row.decided_at!,state.user.timezone)}</time></p>}
    {row.status==="ACCEPTED"&&<p><strong>Closed by mutual agreement</strong></p>}
    {row.status==="REQUESTED"&&row.counterparty.id===data.user&&pendingVerification&&<p role="status">A repayment is pending verification. Resolve it before accepting mutual closure.</p>}
    <div className="button-row">{mutualClosureActions(row,data.user).map(action=>{const pending=data.pending(action,row.id),blockedByVerification=action==="accept"&&pendingVerification;return <Button key={action} variant={action==="accept"?"primary":"secondary"} disabled={data.busy||blockedByVerification||!!pending?.blocked||!!pending?.needsReconcile} onClick={()=>setConfirmation({row,action})}>{pending?"Retry same "+action:action==="accept"?"Accept":action==="reject"?"Reject":"Cancel request"}</Button>;})}</div>
   </Card>)}
  </>}
  {confirmation&&<Confirmation {...confirmation} onCancel={()=>setConfirmation(null)} onConfirm={()=>{const {row,action}=confirmation;setConfirmation(null);void data.decide(row,action).then(result=>{if(result)onChanged();});}}/>}
 </section>;
}
