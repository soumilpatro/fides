"use client";
import { trapConfirmationFocus } from "../f6-dialog";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Extension, ExtensionRequest } from "@fides/shared/api/extensions";
import { canRequestExtension, extensionActions, extensionBody } from "@fides/shared/extensions/model";
import { Button, Card, EmptyState, ErrorState, LoadingState, StatusChip, TextField } from "../../components/ui";
import { useExtensions } from "./useExtensions";
import { useAuth } from "../auth/useAuth";
import { notificationTimestamp as formatTimestamp } from "@fides/shared/notifications/presentation";
import { dateOnlyLabel } from "@fides/shared/dashboard/due-presentation";
function Confirmation({row,action,onCancel,onConfirm}:{row:Extension;action:"accept"|"reject";onCancel:()=>void;onConfirm:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>previous?.focus();},[]);
 return <dialog tabIndex={-1} onKeyDown={trapConfirmationFocus} className="connection-confirm f6-dialog" ref={dialog} aria-labelledby="extension-confirm-title" aria-describedby="extension-confirm-body" onCancel={onCancel}>
 <h2 id="extension-confirm-title">{action==="accept"?"Accept this extension?":"Reject this extension?"}</h2>
 <p id="extension-confirm-body">{action==="accept"?"The commitment due date will change from "+dateOnlyLabel(row.previous_due_date)+" to "+dateOnlyLabel(row.requested_due_date)+".":"The current due date will remain unchanged."}</p>
 <div className="button-row"><Button variant="quiet" autoFocus onClick={onCancel}>Go back</Button><Button variant={action==="accept"?"primary":"secondary"} onClick={onConfirm}>{action==="accept"?"Accept extension":"Reject extension"}</Button></div></dialog>;
}
export function ExtensionsSection({id,onChanged}:{id:string;onChanged:()=>void}){
 const data=useExtensions(id),[confirmation,setConfirmation]=useState<{row:Extension;action:"accept"|"reject"}|null>(null);
 const {state}=useAuth();
 if(state.status!=="authenticated")return null;
 return <section id="due-date-extension" className="f6-stack" aria-labelledby="extensions-title"><h2 id="extensions-title">Due-date extension</h2>
 <Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh extensions</Button>
 {data.busy&&<LoadingState message="Loading due-date requests…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data&&<>{canRequestExtension(data.data.parent,data.data.terms,data.data.rows)&&!data.pending("create")&&<Link className="button button--primary" href={"/app/commitments/"+id+"/extensions/new"}>Request extension</Link>}
 {data.pending("create")&&<Link className="button button--secondary" href={"/app/commitments/"+id+"/extensions/new"}>Review earlier extension request</Link>}
 {!data.data.rows.length&&<EmptyState title="No extension requests" message="A due-date change needs the other participant's acceptance."/>}
 {data.data.rows.map(row=><Card key={row.id}><StatusChip label={row.status==="REQUESTED"&&row.requested_by.id===data.user?"Awaiting response":row.status==="REQUESTED"?"Requested":row.status.charAt(0)+row.status.slice(1).toLowerCase()} status={row.status==="REQUESTED"?"PENDING":undefined}/>
 <p>Requested by {row.requested_by.display_name}</p><dl className="commitment-facts"><dt>Previous due date</dt><dd>{dateOnlyLabel(row.previous_due_date)}</dd><dt>{row.status==="ACCEPTED"?"Accepted due date":"Requested due date"}</dt><dd>{dateOnlyLabel(row.requested_due_date)}</dd></dl>
 {row.reason&&<p className="f6-wrap">{row.reason}</p>}{row.decided_by&&<p>{row.decided_by.display_name} · <time dateTime={row.decided_at!}>{formatTimestamp(row.decided_at!,state.user.timezone)}</time></p>}
 <div className="button-row">{extensionActions(row,data.user,data.data!.parent,data.data!.terms).map(action=>{
 const pending=data.pending(action,row.id),opposite=data.pending(action==="accept"?"reject":"accept",row.id);
 return <Button key={action} variant={action==="accept"?"primary":"secondary"} disabled={data.busy||!!opposite||!!pending?.blocked||!!pending?.needsReconcile} onClick={()=>setConfirmation({row,action})}>{pending?"Retry same "+action:action==="accept"?"Accept extension":"Reject extension"}</Button>;
 })}</div></Card>)}</>}
 {confirmation&&<Confirmation {...confirmation} onCancel={()=>setConfirmation(null)} onConfirm={()=>{const {row,action}=confirmation;setConfirmation(null);void data.decide(row,action).then(result=>{if(result)onChanged();});}}/>}
 </section>;
}
export function NewExtension({id}:{id:string}){
 const data=useExtensions(id),router=useRouter(),[date,setDate]=useState(""),[reason,setReason]=useState(""),[review,setReview]=useState<ExtensionRequest|null>(null),[validation,setValidation]=useState<string|null>(null);
 const pending=data.pending("create"),body=pending?JSON.parse(pending.payload) as ExtensionRequest:review;
 return <div className="f6-stack"><Link href={"/app/commitments/"+id+"#due-date-extension"}>Back to commitment</Link><h1>Request extension</h1>
 <p>This changes the due date only if the other participant accepts.</p>{data.busy&&<LoadingState message="Loading current terms…"/>}{data.error&&<ErrorState message={data.error}/>}
 {validation&&<ErrorState message={validation}/>}
 {data.data&&<><p>Current due date: {data.due?dateOnlyLabel(data.due):"No deadline"}</p>
 {body?<><Card title="Review extension"><p>Requested due date: {dateOnlyLabel(body.requested_due_date)}</p><p className="f6-wrap">{body.reason??"No reason supplied"}</p></Card>
 {pending&&<p role="status">The earlier attempt may have completed. Its original key and payload are retained. Refresh before explicitly retrying.</p>}
 {!pending&&<Button variant="quiet" onClick={()=>setReview(null)} disabled={data.busy}>Edit request</Button>}
 <Button disabled={data.busy||!!pending?.blocked||!!pending?.needsReconcile} onClick={()=>void data.request(body).then(r=>{if(r)router.push("/app/commitments/"+id+"#due-date-extension");})}>{pending?"Retry same request":"Submit extension request"}</Button>
 {pending&&<Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh before retrying</Button>}</>:
 canRequestExtension(data.data.parent,data.data.terms,data.data.rows)?<form className="f6-stack" onSubmit={e=>{e.preventDefault();try{setReview(extensionBody(date,reason,data.due!));setValidation(null);}catch(e){setValidation(e instanceof Error?e.message:"Check the requested date.");}}}>
 <TextField label="Requested due date" type="date" required value={date} disabled={data.busy} onChange={e=>setDate(e.target.value)}/>
 <label className="field">Reason (optional)<textarea value={reason} disabled={data.busy} onChange={e=>setReason(e.target.value)} aria-describedby="extension-reason-count"/></label><small id="extension-reason-count">{Array.from(reason.trim()).length}/500 characters after trimming</small>
 <Button type="submit" disabled={data.busy}>Review extension</Button></form>:<EmptyState title="Extension unavailable" message="Only an eligible single-date commitment without a pending request can request a due-date extension."/>}</>}
 </div>;
}
