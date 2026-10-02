"use client";
import { trapConfirmationFocus } from "../f6-dialog";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button, Card, ErrorState, TextField } from "../../components/ui";
import { useProfile } from "./useProfile";
function Deactivate({busy,error,blocked,onCancel,onDeactivate}:{busy:boolean;error:string|null;blocked:boolean;onCancel:()=>void;onDeactivate:(value:string)=>void}){
 const [typed,setTyped]=useState(""),dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>previous?.focus();},[]);
 return <dialog tabIndex={-1} onKeyDown={trapConfirmationFocus} ref={dialog} className="connection-confirm f6-dialog" aria-labelledby="deactivate-title" aria-describedby="deactivate-body" onCancel={e=>{if(busy)e.preventDefault();else onCancel();}}>
 <h2 id="deactivate-title">Deactivate account?</h2><p id="deactivate-body">Your account will be deactivated. This action is only available when Fides has no unresolved commitments preventing deactivation.</p>
 <TextField label="Type DEACTIVATE to continue." autoComplete="off" autoFocus disabled={busy} value={typed} onChange={e=>setTyped(e.target.value)}/>
 {error&&<ErrorState message={error}/>} {blocked&&<Link className="button button--secondary" href="/app/overview" onClick={onCancel}>Back to commitments</Link>}
 <div className="button-row"><Button variant="quiet" disabled={busy} onClick={onCancel}>Go back</Button><Button variant="destructive" disabled={busy||typed!=="DEACTIVATE"} onClick={()=>onDeactivate(typed)}>{busy?"Deactivating…":"Deactivate account"}</Button></div></dialog>;
}
export function Profile(){
 const data=useProfile(),[editing,setEditing]=useState(false),[name,setName]=useState(""),[timezone,setTimezone]=useState(""),[deactivating,setDeactivating]=useState(false),[validation,setValidation]=useState<string|null>(null);
 if(!data.user)return null;
 const user=data.user;
 const edit=()=>{setName(user.display_name);setTimezone(user.timezone);setValidation(null);setEditing(true);};
 return <div className="f6-stack"><h1>Profile / Settings</h1><Card title="Profile">
 <dl className="commitment-facts"><dt>Display name</dt><dd>{user.display_name}</dd><dt>Phone (read-only)</dt><dd>{user.phone_e164??"Unavailable"}</dd><dt>Timezone</dt><dd>{user.timezone}</dd></dl>
 {editing?<form className="f6-stack" onSubmit={e=>{e.preventDefault();try{new Intl.DateTimeFormat("en",{timeZone:timezone});if(!name.trim())throw new Error("Enter a display name.");setValidation(null);const body={...(name!==user.display_name?{display_name:name}:{}),...(timezone!==user.timezone?{timezone}:{})};void data.save(body).then(ok=>{if(ok)setEditing(false);});}catch{setValidation("Enter a display name and a valid IANA timezone.");}}}>
 <TextField label="Display name" value={name} required disabled={data.busy} onChange={e=>setName(e.target.value)}/>
 <TextField label="Timezone" value={timezone} required list="timezones" hint="Use an IANA timezone. Saving is explicit; your device timezone never replaces this automatically." disabled={data.busy} onChange={e=>setTimezone(e.target.value)}/>
 <datalist id="timezones">{Intl.supportedValuesOf?.("timeZone").map(zone=><option key={zone} value={zone}/>)}</datalist>
 {validation&&<ErrorState message={validation}/>}<div className="button-row"><Button type="submit" disabled={data.busy||name===user.display_name&&timezone===user.timezone}>{data.busy?"Saving…":"Save profile"}</Button><Button variant="quiet" disabled={data.busy} onClick={()=>setEditing(false)}>Cancel edit</Button></div></form>:<Button variant="secondary" disabled={data.busy} onClick={edit}>Edit profile</Button>}
 {data.saved&&<p role="status">Profile saved.</p>}{data.error&&!deactivating&&<ErrorState message={data.error}/>}<Button variant="quiet" disabled={data.busy} onClick={()=>void data.refresh()}>Refresh profile</Button></Card>
 <Card title="Account"><div className="button-row"><Button variant="secondary" disabled={data.busy} onClick={()=>void data.logout()}>Log out</Button><Button variant="destructive" disabled={data.busy} onClick={()=>setDeactivating(true)}>Deactivate account</Button></div></Card>
 {deactivating&&<Deactivate busy={data.busy} error={data.error} blocked={data.blocked} onCancel={()=>setDeactivating(false)} onDeactivate={value=>void data.deactivate(value)}/>}
 </div>;
}
