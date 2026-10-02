"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Connection } from "@fides/shared/api/connections";
import { actionLabel, availableConnectionActions, confirmation, connectionSections, otherParticipant,
  relationshipContext, statusLabel, type ConnectionAction } from "@fides/shared/connections/model";
import { Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, StatusChip, TextField } from "../../components/ui";
import { useConnections } from "./useConnections";
function Feedback({ error, busy }: { error: string | null; busy: boolean }) {
  return <>{error && <ErrorState message={error} />}{busy && <p role="status">Updating from Fides…</p>}</>;
}
export function ConnectionsList() {
  const data = useConnections();
  return <div className="connections-feature">
    <header className="section-heading"><div><p className="eyebrow">People you know</p><h1>Connections</h1>
      <p>Connections let you create shared commitments later.</p></div>
      <Link className="button button--primary" href="/app/connections/new">Add connection</Link></header>
    <Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh connections</Button>
    <Feedback error={data.error} busy={data.busy} />
    {data.rows === null && data.busy && <LoadingState message="Loading connections…" />}
    {data.rows?.length === 0 && <EmptyState title="No connections yet" message="Connect with someone you know to start keeping shared commitments organized." />}
    {data.rows && connectionSections(data.rows, data.userId).map(section => <Card key={section.title} title={section.title}>
      <ul className="connection-list">{section.rows.map(row => {
        const other = otherParticipant(row, data.userId)!;
        return <li key={row.id}><Link className="connection-row" href={"/app/connections/" + row.id} aria-label={"View connection with " + other.display_name}>
          <PersonRow name={other.display_name} role={relationshipContext(row, data.userId)} />
          <StatusChip label={statusLabel[row.status]} /><span className="supporting">View details →</span>
        </Link></li>;
      })}</ul>
    </Card>)}
  </div>;
}
export function NewConnection() {
  const data = useConnections(); const router = useRouter(); const [phone, setPhone] = useState("");
  return <div className="connections-feature">
    <Link className="auth-back" href="/app/connections">← Connections</Link><h1>Add connection</h1>
    <Card><form className="auth-form" onSubmit={event => { event.preventDefault(); if (!phone.trim()) return;
      void data.create(phone).then(row => { if (row) { setPhone(""); router.push("/app/connections/" + row.id); } });
    }}>
      <TextField label="Phone number" hint="Use international format, beginning with +." type="tel" autoComplete="off"
        required value={phone} disabled={data.busy} onChange={event => setPhone(event.target.value)} />
      <p className="supporting">Enter the number of someone you know. Fides does not search your contacts.</p>
      <Feedback error={data.error} busy={data.busy} />
      <Button type="submit" disabled={data.busy || data.uncertain || !phone.trim()}>Send connection request</Button>
      {data.uncertain && <Button variant="quiet" onClick={() => void data.refresh()}>Refresh before retrying</Button>}
    </form></Card>
  </div>;
}
function Confirm({ action, row, onCancel, onConfirm }: {
  action: ConnectionAction; row: Connection; onCancel: () => void; onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null); const copy = confirmation(action, row);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="connection-confirm" aria-labelledby="confirm-title" aria-describedby="confirm-body" onCancel={onCancel}>
    <h2 id="confirm-title">{copy.title}</h2><p id="confirm-body">{copy.body}</p>
    <div className="button-row"><Button variant="quiet" autoFocus onClick={onCancel}>Cancel</Button>
      <Button variant={action === "accept" ? "primary" : "secondary"} onClick={onConfirm}>{copy.button}</Button></div>
  </dialog>;
}
export function ConnectionDetail({ id }: { id: string }) {
  const data = useConnections(id); const [pending, setPending] = useState<ConnectionAction | null>(null);
  const row = data.detail; const other = row && otherParticipant(row, data.userId);
  const date = (value: string) => new Date(value).toLocaleString();
  return <div className="connections-feature">
    <Link className="auth-back" href="/app/connections">← Connections</Link><h1>Connection detail</h1>
    <Button variant="quiet" disabled={data.busy} onClick={() => void data.refresh()}>Refresh connection</Button>
    <Feedback error={data.error} busy={data.busy} />
    {!row && data.busy && <LoadingState message="Loading connection…" />}
    {row && other && <Card>
      <PersonRow name={other.display_name} role={relationshipContext(row, data.userId)} />
      <StatusChip label={statusLabel[row.status]} />
      <dl className="connection-dates"><div><dt>Created</dt><dd><time dateTime={row.created_at}>{date(row.created_at)}</time></dd></div>
        <div><dt>Updated</dt><dd><time dateTime={row.updated_at}>{date(row.updated_at)}</time></dd></div></dl>
      {row.status === "BLOCKED" && <p>This connection is blocked. Fides does not currently provide an unblock action.</p>}
      {row.status === "REMOVED" && <><p>This connection is removed. To send a new request, enter the phone number again.</p>
        <Link className="button button--secondary" href="/app/connections/new">Send new request</Link></>}
      <div className="button-row">{availableConnectionActions(row, data.userId).map(action =>
        <Button key={action} variant={action === "accept" ? "primary" : "secondary"} disabled={data.busy || data.uncertain}
          onClick={() => setPending(action)}>{actionLabel(action, row)}</Button>)}</div>
      {pending && <Confirm action={pending} row={row} onCancel={() => setPending(null)}
        onConfirm={() => { setPending(null); void data.action(pending, row); }} />}
    </Card>}
  </div>;
}
