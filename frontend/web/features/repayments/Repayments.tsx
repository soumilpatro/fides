"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Repayment, RepaymentRequest, DecisionRequest } from "@fides/shared/api/repayments";
import { formatMoney } from "@fides/shared/domain/money";
import { canReport, canDecide, labels, semantics, reportBody, decisionBody, decisionCopy, type DecisionAction } from "@fides/shared/repayments/model";
import { statusLabels } from "@fides/shared/commitments/model";
import { dateOnlyLabel } from "@fides/shared/dashboard/due-presentation";
import { Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, StatusChip, TextField } from "../../components/ui";
import { useRepayments } from "./useRepayments";
import { useAuth } from "../auth/useAuth";
import { notificationTimestamp as formatTimestamp } from "@fides/shared/notifications/presentation";
import { trapConfirmationFocus } from "../f6-dialog";
function Feedback({error,busy}:{error:string|null;busy:boolean}) { return <>{error && <ErrorState message={error}/>} {busy && <LoadingState message="Loading the authoritative repayment record…"/>}</>; }
function Facts({row}:{row:Repayment}) { const {state}=useAuth(); if(state.status!=="authenticated")return null; return <><PersonRow name={row.reported_by.display_name} role="Reported by"/><strong className="amount amount--card">{formatMoney(row.amount_minor,row.currency)}</strong><StatusChip label={labels[row.status]} status={semantics[row.status]}/>
  <dl className="commitment-facts"><dt>Payment date</dt><dd>{dateOnlyLabel(row.payment_date)}</dd><dt>Reported at</dt><dd><time dateTime={row.reported_at}>{formatTimestamp(row.reported_at,state.user.timezone)}</time></dd><dt>Note</dt><dd>{row.note || "No note"}</dd></dl>
  {row.status === "PENDING_VERIFICATION" && <p className="supporting">Reported, not yet verified. The other participant still needs to verify or dispute this repayment.</p>}</>; }
export function RepaymentsSection({id}:{id:string}) {
  const data=useRepayments(id);
  return <section className="commitments-feature" aria-label="Repayments"><h2>Repayments</h2><Feedback error={data.error} busy={data.busy}/>
    <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh repayments</Button>
    {data.fresh && data.data && canReport(data.data.parent,data.userId) && <Link className="button button--primary" href={"/app/commitments/"+id+"/repayments/new"}>Report repayment</Link>}
    {data.data?.rows.length === 0 && <EmptyState title="No repayments reported" message="Reported repayments will appear here as separate records."/>}
    {data.data?.rows.map(row=><Card key={row.id}><Facts row={row}/><Link className="button button--quiet" href={"/app/repayments/"+row.id}>View repayment reported by {row.reported_by.display_name} · {formatMoney(row.amount_minor,row.currency)} · {dateOnlyLabel(row.payment_date)}</Link></Card>)}
  </section>;
}
export function ReportRepayment({id}:{id:string}) {
  const data=useRepayments(id),router=useRouter();
  const [form,setForm]=useState({amount:"",date:"",note:""}),[review,setReview]=useState<RepaymentRequest|null>(null),[validation,setValidation]=useState<string|null>(null);
  const pending=data.pending("report"),body=pending ? JSON.parse(pending.payload) as RepaymentRequest : review,parent=data.data?.parent;
  const eligible=!!parent && data.fresh && canReport(parent,data.userId);
  return <div className="commitments-feature"><Link className="auth-back" href={"/app/commitments/"+id}>← Commitment</Link><h1>Report repayment</h1><Feedback error={data.error} busy={data.busy}/>{validation && <ErrorState message={validation}/>}
    <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh record</Button>
    {parent && <p>Commitment currency: <strong>{parent.currency}</strong> · {statusLabels[parent.status]}</p>}
    {parent && data.fresh && !canReport(parent,data.userId) && <ErrorState message="This commitment does not currently allow repayment reporting."/>}
    {body ? <><Card title="Review repayment"><strong className="amount amount--card">{formatMoney(body.amount_minor,body.currency)}</strong><p>Payment date: {dateOnlyLabel(body.payment_date)}</p><p>Note: {body.note || "No note"}</p>
      <p>You are reporting this repayment.</p><p>It will remain pending until the other participant verifies or disputes it.</p><p className="supporting">Fides records this repayment. Money moves outside Fides.</p></Card>
      {pending && <p role="status">The earlier attempt may have completed. Its original key and payload are retained; only an explicit same-request retry is allowed after refresh.</p>}
      {!pending && <Button variant="quiet" disabled={data.busy} onClick={()=>setReview(null)}>Edit report</Button>}
      <Button disabled={data.busy || !eligible || !!pending?.blocked || !!pending?.needsReconcile} onClick={()=>{void data.report(body).then(row=>{if(row)router.push("/app/repayments/"+row.id);});}}>{pending ? "Retry same report" : "Report repayment"}</Button></> : parent && <form className="commitment-form" onSubmit={event=>{event.preventDefault();try{setReview(reportBody(form,parent));setValidation(null);}catch(error){setValidation(error instanceof Error ? error.message : "Check the report fields.");}}}>
      <fieldset disabled={data.busy || !eligible}><legend>Repayment record</legend><TextField label={"Amount ("+parent.currency+")"} inputMode="decimal" value={form.amount} hint="Positive amount, up to two fractional digits. Currency is locked to the commitment." onChange={e=>setForm({...form,amount:e.target.value})}/>
      <TextField label="Payment date" type="date" value={form.date} hint="Date only. The server checks the date in your account timezone." onInput={e=>{const date=e.currentTarget.value;setForm(previous=>({...previous,date}));}} onChange={e=>{const date=e.target.value;setForm(previous=>({...previous,date}));}}/>
      <label className="field">Note (optional)<textarea value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/><small>{Array.from(form.note.trim()).length}/500 characters after trimming</small></label></fieldset>
      <Button type="submit" disabled={data.busy || !eligible}>Review repayment</Button></form>}
  </div>;
}
function Confirmation({action,onCancel,onSubmit}:{action:DecisionAction;onCancel:()=>void;onSubmit:(body:DecisionRequest)=>void}) {
  const dialog=useRef<HTMLDialogElement>(null),[note,setNote]=useState(""),[error,setError]=useState<string|null>(null),copy=decisionCopy(action);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>previous?.focus();},[]);
  return <dialog tabIndex={-1} className="connection-confirm f6-dialog" ref={dialog} aria-labelledby="decision-title" aria-describedby="decision-body" onKeyDown={trapConfirmationFocus} onCancel={onCancel}><h2 id="decision-title">{copy.title}</h2><p id="decision-body">{copy.body}</p><p>{copy.support}</p>
    <form onSubmit={event=>{event.preventDefault();try{onSubmit(decisionBody(note));}catch(error){setError(error instanceof Error ? error.message : "Check the note.");}}}>
      <label className="field">Note (optional)<textarea value={note} onChange={e=>setNote(e.target.value)} aria-describedby="decision-hint"/><small id="decision-hint">{copy.hint} {Array.from(note.trim()).length}/500</small></label>
      {error && <ErrorState message={error}/>}<div className="button-row"><Button variant="quiet" autoFocus onClick={onCancel}>Go back</Button><Button type="submit" variant={action === "dispute" ? "secondary" : "primary"}>{copy.button}</Button></div></form>
  </dialog>;
}
export function RepaymentDetail({id}:{id:string}) {
  const data=useRepayments(undefined,id),[confirmation,setConfirmation]=useState<DecisionAction|null>(null),row=data.data?.detail,parent=data.data?.parent;
  const {state}=useAuth();
  const eligible=!!row && !!parent && data.fresh && canDecide(row,parent,data.userId);
  if(state.status!=="authenticated")return null;
  return <div className="commitments-feature">{parent && <Link className="auth-back" href={"/app/commitments/"+parent.id}>← Commitment</Link>}<h1>Repayment detail</h1>
    <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh repayment and history</Button><Feedback error={data.error} busy={data.busy}/>
    {row && <><Card><Facts row={row}/></Card>{parent && <p>Commitment: {statusLabels[parent.status]}</p>}
      {row.status === "PENDING_VERIFICATION" && row.reported_by.id === data.userId && <p>You reported this repayment. Only the other participant can verify or dispute it.</p>}
      {eligible && <div className="button-row">{(["verify","dispute"] as const).map(action=>{const pending=data.pending(action);return <Button key={action} variant={action === "dispute" ? "secondary" : "primary"} disabled={data.busy || data.actionBlocked(action) || !!pending?.blocked || !!pending?.needsReconcile}
        onClick={()=>{if(pending)void data.decide(action,JSON.parse(pending.payload));else setConfirmation(action);}}>{pending ? "Retry same "+action : decisionCopy(action).button}</Button>;})}</div>}
      {(["verify","dispute"] as const).some(action=>data.pending(action)) && <p role="status">An earlier decision may have completed. Refresh the record and history before explicitly retrying the original decision. The opposite action remains unavailable.</p>}
      <Card title="Verification history">{data.data?.history ? data.data.history.length ? data.data.history.map(entry=><div key={entry.id}><PersonRow name={entry.decided_by.display_name} role="Decision by"/><StatusChip label={labels[entry.decision]} status={semantics[entry.decision]}/><p><time dateTime={entry.decided_at}>{formatTimestamp(entry.decided_at,state.user.timezone)}</time></p><p>{entry.decision_note || "No decision note"}</p></div>) : <p>No verification or dispute decision yet.</p> : <p>Refresh to load current history.</p>}</Card>
      {confirmation && <Confirmation action={confirmation} onCancel={()=>setConfirmation(null)} onSubmit={body=>{const action=confirmation;setConfirmation(null);void data.decide(action,body);}}/>}
    </>}
  </div>;
}
