"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { CommitmentRequest, Terms } from "@fides/shared/api/commitments";
import { formatMoney } from "@fides/shared/domain/money";
import { initialForm, proposalBody, type ProposalForm } from "@fides/shared/commitments/form";
import { percentText } from "@fides/shared/commitments/money";
import { commitmentRole, counterparty, currentTerms, proposalActions, proposalContext, proposalConfirmation, scheduleText, statusLabels, type ProposalAction } from "@fides/shared/commitments/model";
import { otherParticipant } from "@fides/shared/connections/model";
import { Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, StatusChip, TextField } from "../../components/ui";
import { useCommitments } from "./useCommitments";
import { ExtensionsSection } from "../extensions/Extensions";
import { History } from "../dashboard/Dashboard";
import { RepaymentsSection } from "../repayments/Repayments";
import { MutualClosureSection } from "../mutual-closure/MutualClosure";
import { useAuth } from "../auth/useAuth";
import { trapConfirmationFocus } from "../f6-dialog";
import { dateOnlyLabel } from "@fides/shared/dashboard/due-presentation";
function Feedback({ error, busy }: { error: string | null; busy: boolean }) {
  return <>{error && <ErrorState message={error} />}{busy && <LoadingState message="Loading the authoritative record…" />}</>;
}
export function CommitmentsList({dashboard=false}:{dashboard?:boolean}) {
  const data = useCommitments();
  return <div className="commitments-feature"><header className="section-heading"><div><p className="eyebrow">Shared records</p>{dashboard?<h2>Commitments</h2>:<h1>Commitments</h1>}</div>
    <Link className="button button--primary" href="/app/commitments/new">Create commitment</Link></header>
    <Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh commitments</Button>
    <Feedback error={data.error} busy={data.busy} />
    {data.data?.rows.length === 0 && <EmptyState title="No commitments yet" message="Create a shared record with someone you're connected to." />}
    {data.data?.rows.map(row => <Card key={row.id}><PersonRow name={counterparty(row, data.userId)!.display_name} role={"You are the " + commitmentRole(row, data.userId)!.toLowerCase()} />
      <div className="commitment-row"><strong className="amount amount--row">{formatMoney(row.principal_amount_minor, row.currency)}</strong>
        <span>{row.type === "IOU" ? "IOU" : "Peer loan"}</span><StatusChip label={statusLabels[row.status]} /></div>
      <p>{proposalContext(row, data.userId)}</p>{row.description && <p>{row.description}</p>}
      <Link className="button button--quiet" href={"/app/commitments/" + row.id}>View commitment with {counterparty(row, data.userId)!.display_name}</Link>
    </Card>)}</div>;
}
function Review({ body, name, self }: { body: CommitmentRequest; name: string; self: string }) {
  return <Card title="Review proposal"><p><strong>{body.actor_role === "BORROWER" ? "You are borrowing from " : "You are lending to "}{name}</strong></p>
    <dl className="commitment-facts"><dt>Borrower</dt><dd>{body.actor_role === "BORROWER" ? self : name}</dd><dt>Lender</dt><dd>{body.actor_role === "LENDER" ? self : name}</dd>
      <dt>Type</dt><dd>{body.type === "IOU" ? "IOU" : "Peer loan"}</dd><dt>Principal</dt><dd>{formatMoney(body.principal_amount_minor, body.currency)}</dd>
      <dt>Description</dt><dd>{body.description || "No description"}</dd><dt>Schedule</dt><dd>{body.terms.installment_dates ? body.terms.installment_dates.map(dateOnlyLabel).join(", ") : body.terms.due_date ? "Due " + dateOnlyLabel(body.terms.due_date) : "No deadline"}</dd>
      <dt>Interest</dt><dd>{body.terms.interest_type === "NONE" ? "No interest" : "Simple fixed: " + percentText(body.terms.interest_rate_bps!)}</dd>
      <dt>Grace period</dt><dd>{body.terms.grace_period_days} days</dd></dl>
    <p className="supporting">Fides records the commitment. Money moves outside Fides. Interest totals and installment amounts come from the server after creation.</p>
  </Card>;
}
export function NewCommitment({ selected = "" }: { selected?: string }) {
  const data = useCommitments(undefined, true), router = useRouter(), { state } = useAuth();
  const [form, setForm] = useState(() => initialForm(selected));
  const [review, setReview] = useState<CommitmentRequest | null>(null), [validation, setValidation] = useState<string | null>(null);
  const pending = data.pending("create");
  const body = pending ? JSON.parse(pending.payload) as CommitmentRequest : review;
  const eligible = data.data?.eligible ?? [];
  const connection = eligible.find(row => row.id === (body?.connection_id ?? form.connection));
  const name = connection ? otherParticipant(connection, data.userId)?.display_name ?? "Selected participant" : "Selected participant";
  const set = <K extends keyof ProposalForm>(field: K, value: ProposalForm[K]) => { setForm(previous => ({ ...previous, [field]: value })); setValidation(null); };
  const submit = () => { if (body) void data.create(body).then(row => { if (row) router.push("/app/commitments/" + row.id); }); };
  return <div className="commitments-feature"><Link className="auth-back" href="/app/overview">← Commitments</Link><h1>Create commitment</h1>
    <Feedback error={data.error} busy={data.busy} />{validation && <ErrorState message={validation} />}
    {body ? <><Review body={body} name={name} self={state.status === "authenticated" ? state.user.display_name : "You"} />
      {pending && <p role="status">An earlier attempt may have completed. Refresh before explicitly retrying the same proposal; its key and payload are retained.</p>}
      {!pending && <Button variant="quiet" disabled={data.busy} onClick={() => setReview(null)}>Edit proposal</Button>}
      <Button disabled={data.busy || !!pending?.blocked || !!pending?.needsReconcile} onClick={submit}>{pending ? "Retry same proposal" : "Submit proposal"}</Button>
      {pending && <Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh before retrying</Button>}</> :
      data.data && !eligible.length ? <><EmptyState title="Accepted connection required" message="You need an accepted connection before you can create a commitment." />
        <Link className="button button--primary" href="/app/connections">Go to Connections</Link><Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh accepted connections</Button></> :
      data.data && <form className="commitment-form" onSubmit={event => { event.preventDefault(); try { setReview(proposalBody(form, eligible.map(row => row.id))); setValidation(null); } catch (error) { setValidation(error instanceof Error ? error.message : "Check the proposal fields."); } }}>
        <fieldset disabled={data.busy}><legend>Person and commitment</legend>
          <label className="field">Accepted connection<select required value={form.connection} onChange={event => set("connection",event.target.value)}><option value="">Choose a person</option>
            {eligible.map(row => <option key={row.id} value={row.id}>{otherParticipant(row,data.userId)?.display_name}</option>)}</select></label>
          <fieldset><legend>Your role</legend>{(["BORROWER","LENDER"] as const).map(role => <label className="choice" key={role}><input type="radio" name="role" checked={form.role === role} onChange={() => set("role",role)} />{role === "BORROWER" ? "I am borrowing" : "I am lending"}</label>)}</fieldset>
          <fieldset><legend>Type</legend>{(["IOU","PEER_LOAN"] as const).map(type => <label className="choice" key={type}><input type="radio" name="type" checked={form.type === type} onChange={() => set("type",type)} />{type === "IOU" ? "IOU" : "Peer loan"}</label>)}</fieldset>
          <TextField label="Principal amount" inputMode="decimal" value={form.amount} hint={"Amount in " + form.currency + ". Up to two fractional digits."} onChange={event => set("amount",event.target.value)} />
          <label className="field">Currency<select value={form.currency} onChange={event => set("currency",event.target.value as ProposalForm["currency"])}>{["INR","USD","GBP"].map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="field">Description (optional)<textarea value={form.description} onChange={event => set("description",event.target.value)} aria-describedby="description-count" /><small id="description-count">{Array.from(form.description.trim()).length}/500 characters after trimming</small></label>
        </fieldset>
        <fieldset disabled={data.busy}><legend>Initial terms</legend>
          <fieldset><legend>Schedule</legend>{(["none","single","installments"] as const).map(value => <label className="choice" key={value}><input type="radio" name="schedule" checked={form.schedule === value} onChange={() => set("schedule",value)} />{{none:"No deadline",single:"Single due date",installments:"Installment schedule"}[value]}</label>)}</fieldset>
          {form.schedule === "single" && <TextField label="Due date" type="date" value={form.due} onChange={event => set("due",event.target.value)} />}
          {form.schedule === "installments" && <div className="installment-entry">{form.dates.map((value,index) => <div key={index} className="installment-date-row">
            <TextField label={"Installment date " + (index+1)} type="date" value={value} onChange={event => set("dates",form.dates.map((date,i) => i === index ? event.target.value : date))} />
            <Button variant="quiet" disabled={form.dates.length <= 2} onClick={() => set("dates",form.dates.filter((_,i) => i !== index))}>Remove date {index+1}</Button></div>)}
            <Button variant="quiet" disabled={form.dates.length >= 60} onClick={() => set("dates",[...form.dates,""])}>Add installment date</Button><p>2–60 dates, strictly increasing. Amounts are assigned by the server.</p></div>}
          <fieldset><legend>Interest</legend>{(["NONE","SIMPLE_FIXED"] as const).map(value => <label className="choice" key={value}><input type="radio" name="interest" checked={form.interest === value} onChange={() => set("interest",value)} />{value === "NONE" ? "No interest" : "Simple fixed interest"}</label>)}</fieldset>
          {form.interest === "SIMPLE_FIXED" && <TextField label="Fixed interest percentage" inputMode="decimal" hint="0.01%–100%, up to two fractional digits." value={form.percent} onChange={event => set("percent",event.target.value)} />}
          <TextField label="Grace period (days)" inputMode="numeric" value={form.grace} onChange={event => set("grace",event.target.value)} hint="Integer from 0 to 365." />
        </fieldset><Button type="submit" disabled={data.busy}>Review proposal</Button>
      </form>}
  </div>;
}
function TermsView({ terms }: { terms: Terms }) {
  const v = currentTerms(terms);
  return <Card title="Current terms"><p>{scheduleText(v)}</p>{v.installment_dates && <ul>{v.installment_dates.map(date => <li key={date}>{dateOnlyLabel(date)}</li>)}</ul>}
    <dl className="commitment-facts"><dt>Interest</dt><dd>{v.interest_type === "NONE" ? "No interest" : "Simple fixed: " + percentText(v.interest_rate_bps!)}</dd>
      <dt>Grace period</dt><dd>{v.grace_period_days} days</dd><dt>Due timezone</dt><dd>{v.due_timezone ?? "Timezone not recorded for these legacy terms."}</dd>
      <dt>Version</dt><dd>{v.version_no}</dd></dl></Card>;
}
function Confirm({ action, name, onCancel, onConfirm }: { action: ProposalAction; name: string; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null), copy = proposalConfirmation(action,name);
  useEffect(() => { const previous=document.activeElement as HTMLElement|null; dialog.current?.showModal(); return()=>previous?.focus(); }, []);
  return <dialog tabIndex={-1} className="connection-confirm f6-dialog" ref={dialog} aria-labelledby="proposal-confirm-title" aria-describedby="proposal-confirm-body" onKeyDown={trapConfirmationFocus} onCancel={onCancel}>
    <h2 id="proposal-confirm-title">{copy.title}</h2><p id="proposal-confirm-body">{copy.body}</p><div className="button-row"><Button variant="quiet" autoFocus onClick={onCancel}>Go back</Button><Button onClick={onConfirm}>{copy.button}</Button></div></dialog>;
}
export function CommitmentDetail({ id }: { id: string }) {
  const [revision,setRevision]=useState(0);
  const data = useCommitments(id), [confirmation, setConfirmation] = useState<ProposalAction | null>(null);
  const row = data.data?.detail, other = row && counterparty(row,data.userId);
  return <div className="commitments-feature"><Link className="auth-back" href="/app/overview">← Commitments</Link><h1>Commitment detail</h1>
    <Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh commitment</Button><Feedback busy={data.busy} error={data.error} />
    {row && other && <><Card><PersonRow name={other.display_name} role={"You are the " + commitmentRole(row,data.userId)!.toLowerCase()} />
      <StatusChip label={statusLabels[row.status]} /><p>{proposalContext(row,data.userId)}</p>
      <strong className="amount amount--card">{formatMoney(row.principal_amount_minor,row.currency)}</strong>
      <p>{row.type === "IOU" ? "IOU" : "Peer loan"}</p><p>{row.description || "No description"}</p>
      <p className="supporting">Fides records the commitment. Money moves outside Fides.</p></Card>
      {data.data?.terms && <TermsView terms={data.data.terms} />}
      {data.data?.installments && <Card title="Installment schedule">{data.data.installments.map(item => <div key={item.id} className="installment-display">
        <h3>Installment {item.sequence_no} · {dateOnlyLabel(item.due_date)}</h3><StatusChip label={item.status.replaceAll("_"," ")} />
        <dl className="commitment-facts"><dt>Principal</dt><dd>{formatMoney(item.principal_amount_minor,item.currency)}</dd><dt>Interest</dt><dd>{formatMoney(item.interest_amount_minor,item.currency)}</dd><dt>Total due</dt><dd>{formatMoney(item.total_due_minor,item.currency)}</dd></dl></div>)}</Card>}
      <ExtensionsSection id={row.id} onChanged={()=>{setRevision(v=>v+1);void data.refresh();}}/><RepaymentsSection id={row.id}/><MutualClosureSection id={row.id} onChanged={()=>{setRevision(v=>v+1);void data.refresh();}}/><History key={row.id+":"+revision} id={row.id}/>
      <div className="button-row">{proposalActions(row,data.userId).map(action => {
        const pending = data.pending(action);
        return <Button key={action} disabled={data.busy || data.actionBlocked(action) || !data.data?.terms || !!pending?.blocked || !!pending?.needsReconcile}
          onClick={() => setConfirmation(action)}>{pending ? "Retry same " + action : {confirm:"Confirm commitment",reject:"Reject proposal",cancel:"Cancel proposal"}[action]}</Button>;
      })}</div>
      {confirmation && <Confirm action={confirmation} name={other.display_name} onCancel={() => setConfirmation(null)}
        onConfirm={() => { setConfirmation(null); void data.action(confirmation); }} />}
    </>}
  </div>;
}
