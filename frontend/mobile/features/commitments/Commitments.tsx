import { useState } from "react";
import { Modal, Pressable, StyleSheet, View } from "react-native";
import { colors, controls, radii, spacing } from "@fides/shared/tokens/index";
import type { CommitmentRequest, Terms } from "@fides/shared/api/commitments";
import { formatMoney } from "@fides/shared/domain/money";
import { initialForm, proposalBody, type ProposalForm } from "@fides/shared/commitments/form";
import { percentText } from "@fides/shared/commitments/money";
import { commitmentRole, counterparty, currentTerms, proposalActions, proposalContext, proposalConfirmation, scheduleText, statusLabels, type ProposalAction } from "@fides/shared/commitments/model";
import { otherParticipant } from "@fides/shared/connections/model";
import { Body, Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, Screen, StatusChip, TextField, Title } from "../../components/ui";
import { useCommitments } from "./useCommitments";
import { useAuth } from "../auth/useAuth";
type Destination = { page: "list" } | { page: "new"; connection?: string } | { page: "detail"; id: string };
export function Commitments({ initialConnection, onConnections }: { initialConnection?: string; onConnections: () => void }) {
  const [destination, setDestination] = useState<Destination>(() => initialConnection ? { page: "new", connection: initialConnection } : { page: "list" });
  const back = () => setDestination({page:"list"});
  return destination.page === "new" ? <NewCommitment selected={destination.connection} onBack={back} onConnections={onConnections} onDetail={id => setDestination({page:"detail",id})} /> :
    destination.page === "detail" ? <CommitmentDetail key={destination.id} id={destination.id} onBack={back} /> :
    <CommitmentsList onNew={() => setDestination({page:"new"})} onDetail={id => setDestination({page:"detail",id})} />;
}
function Feedback({ error, busy }: { error: string | null; busy: boolean }) {
  return <>{error && <ErrorState message={error} />}{busy && <LoadingState message="Loading the authoritative record…" />}</>;
}
function CommitmentsList({ onNew, onDetail }: { onNew: () => void; onDetail: (id:string) => void }) {
  const data = useCommitments();
  return <Screen><Title>Commitments</Title><Button title="Create commitment" onPress={onNew} />
    <Button title="Refresh commitments" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} /><Feedback error={data.error} busy={data.busy} />
    {data.data?.rows.length === 0 && <EmptyState title="No commitments yet" message="Create a shared record with someone you're connected to." />}
    {data.data?.rows.map(row => <Card key={row.id}><PersonRow name={counterparty(row,data.userId)!.display_name} role={"You are the " + commitmentRole(row,data.userId)!.toLowerCase()} />
      <Body>{formatMoney(row.principal_amount_minor,row.currency)}</Body><Body>{row.type === "IOU" ? "IOU" : "Peer loan"}</Body>
      <StatusChip label={statusLabels[row.status]} /><Body>{proposalContext(row,data.userId)}</Body>{row.description && <Body supporting>{row.description}</Body>}
      <Button title={"View commitment with " + counterparty(row,data.userId)!.display_name} variant="quiet" onPress={() => onDetail(row.id)} />
    </Card>)}</Screen>;
}
function Choice({ label, checked, onPress }: { label: string; checked: boolean; onPress: () => void }) {
  return <Pressable accessibilityRole="radio" accessibilityLabel={label} accessibilityState={{checked}} onPress={onPress} style={[styles.choice,checked && styles.selected]}>
    <Body>{checked ? "Selected: " : ""}{label}</Body>
  </Pressable>;
}
function Review({ body, name, self }: { body: CommitmentRequest; name: string; self: string }) {
  return <Card title="Review proposal"><Body>{body.actor_role === "BORROWER" ? "You are borrowing from " : "You are lending to "}{name}</Body>
    <Body>Borrower: {body.actor_role === "BORROWER" ? self : name}</Body><Body>Lender: {body.actor_role === "LENDER" ? self : name}</Body>
    <Body>Type: {body.type === "IOU" ? "IOU" : "Peer loan"}</Body><Body>Principal: {formatMoney(body.principal_amount_minor,body.currency)}</Body>
    <Body>Description: {body.description || "No description"}</Body>
    <Body>Schedule: {body.terms.installment_dates ? body.terms.installment_dates.join(", ") : body.terms.due_date ? "Due " + body.terms.due_date : "No deadline"}</Body>
    <Body>Interest: {body.terms.interest_type === "NONE" ? "No interest" : "Simple fixed: " + percentText(body.terms.interest_rate_bps!)}</Body>
    <Body>Grace period: {body.terms.grace_period_days} days</Body>
    <Body supporting>Fides records the commitment. Money moves outside Fides. Interest totals and installment amounts come from the server after creation.</Body>
  </Card>;
}
function NewCommitment({ selected, onBack, onDetail, onConnections }: { selected?: string; onBack: () => void; onDetail: (id:string) => void; onConnections: () => void }) {
  const data = useCommitments(undefined,true), {state} = useAuth();
  const [form,setForm] = useState(() => initialForm(selected));
  const [review,setReview] = useState<CommitmentRequest | null>(null), [validation,setValidation] = useState<string | null>(null);
  const pending = data.pending("create"), body = pending ? JSON.parse(pending.payload) as CommitmentRequest : review;
  const eligible = data.data?.eligible ?? [], connection = eligible.find(row => row.id === (body?.connection_id ?? form.connection));
  const name = connection ? otherParticipant(connection,data.userId)?.display_name ?? "Selected participant" : "Selected participant";
  const set = <K extends keyof ProposalForm>(field: K, value: ProposalForm[K]) => { setForm(previous => ({...previous,[field]:value})); setValidation(null); };
  return <Screen><Button title="Back to Commitments" variant="quiet" onPress={onBack} /><Title>Create commitment</Title><Feedback error={data.error} busy={data.busy} />
    {validation && <ErrorState message={validation} />}
    {body ? <><Review body={body} name={name} self={state.status === "authenticated" ? state.user.display_name : "You"} />
      {pending && <Body>An earlier attempt may have completed. Refresh before explicitly retrying the same proposal; its key and payload are retained.</Body>}
      {!pending && <Button title="Edit proposal" variant="quiet" disabled={data.busy} onPress={() => setReview(null)} />}
      <Button title={pending ? "Retry same proposal" : "Submit proposal"} disabled={data.busy || !!pending?.blocked || !!pending?.needsReconcile}
        onPress={() => { void data.create(body).then(row => {if(row) onDetail(row.id);}); }} />
      {pending && <Button title="Refresh before retrying" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} />}</> :
      data.data && !eligible.length ? <><EmptyState title="Accepted connection required" message="You need an accepted connection before you can create a commitment." /><Button title="Go to Connections" onPress={onConnections} />
        <Button title="Refresh accepted connections" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} /></> :
      data.data && <View style={styles.form} pointerEvents={data.busy ? "none" : "auto"}>
        <Card title="Accepted connection">{eligible.map(row => <Choice key={row.id} label={otherParticipant(row,data.userId)!.display_name} checked={row.id === form.connection} onPress={() => set("connection",row.id)} />)}</Card>
        <Card title="Your role">{(["BORROWER","LENDER"] as const).map(role => <Choice key={role} label={role === "BORROWER" ? "I am borrowing" : "I am lending"} checked={form.role === role} onPress={() => set("role",role)} />)}</Card>
        <Card title="Type">{(["IOU","PEER_LOAN"] as const).map(type => <Choice key={type} label={type === "IOU" ? "IOU" : "Peer loan"} checked={form.type === type} onPress={() => set("type",type)} />)}</Card>
        <TextField label="Principal amount" hint={"Amount in " + form.currency + ". Up to two fractional digits."} keyboardType="decimal-pad" value={form.amount} onChangeText={value => set("amount",value)} />
        <Card title="Currency">{(["INR","USD","GBP"] as const).map(currency => <Choice key={currency} label={currency} checked={form.currency === currency} onPress={() => set("currency",currency)} />)}</Card>
        <TextField label="Description (optional)" multiline value={form.description} onChangeText={value => set("description",value)} hint={Array.from(form.description.trim()).length + "/500 characters after trimming"} />
        <Card title="Schedule">{(["none","single","installments"] as const).map(schedule => <Choice key={schedule} label={{none:"No deadline",single:"Single due date",installments:"Installment schedule"}[schedule]} checked={form.schedule === schedule} onPress={() => set("schedule",schedule)} />)}</Card>
        {form.schedule === "single" && <TextField label="Due date" hint="YYYY-MM-DD, date only." autoCapitalize="none" value={form.due} onChangeText={value => set("due",value)} />}
        {form.schedule === "installments" && <Card title="Installment dates">{form.dates.map((date,index) => <View key={index} style={styles.form}>
          <TextField label={"Installment date " + (index+1)} hint="YYYY-MM-DD, strictly increasing." value={date} onChangeText={value => set("dates",form.dates.map((d,i) => i === index ? value : d))} />
          <Button title={"Remove date " + (index+1)} variant="quiet" disabled={form.dates.length <= 2} onPress={() => set("dates",form.dates.filter((_,i) => i !== index))} /></View>)}
          <Button title="Add installment date" variant="quiet" disabled={form.dates.length >= 60} onPress={() => set("dates",[...form.dates,""])} /><Body supporting>2–60 dates. Amounts are assigned by the server.</Body></Card>}
        <Card title="Interest">{(["NONE","SIMPLE_FIXED"] as const).map(interest => <Choice key={interest} label={interest === "NONE" ? "No interest" : "Simple fixed interest"} checked={form.interest === interest} onPress={() => set("interest",interest)} />)}</Card>
        {form.interest === "SIMPLE_FIXED" && <TextField label="Fixed interest percentage" hint="0.01%–100%, up to two fractional digits." keyboardType="decimal-pad" value={form.percent} onChangeText={value => set("percent",value)} />}
        <TextField label="Grace period (days)" hint="Integer from 0 to 365." keyboardType="number-pad" value={form.grace} onChangeText={value => set("grace",value)} />
        <Button title="Review proposal" disabled={data.busy} onPress={() => {try { setReview(proposalBody(form,eligible.map(row => row.id))); setValidation(null); } catch (error) {setValidation(error instanceof Error ? error.message : "Check the proposal fields.");}}} />
      </View>}
  </Screen>;
}
function TermsView({ terms }: { terms: Terms }) {
  const v = currentTerms(terms);
  return <Card title="Current terms"><Body>{scheduleText(v)}</Body>{v.installment_dates?.map(date => <Body key={date}>{date}</Body>)}
    <Body>Interest: {v.interest_type === "NONE" ? "No interest" : "Simple fixed: " + percentText(v.interest_rate_bps!)}</Body>
    <Body>Grace period: {v.grace_period_days} days</Body><Body>Due timezone: {v.due_timezone ?? "Timezone not recorded for these legacy terms."}</Body><Body supporting>Version: {v.version_no}</Body></Card>;
}
function CommitmentDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const data = useCommitments(id), [confirmation,setConfirmation] = useState<ProposalAction | null>(null);
  const row = data.data?.detail, other = row && counterparty(row,data.userId);
  const copy = confirmation && other ? proposalConfirmation(confirmation,other.display_name) : null;
  return <Screen><Button title="Back to Commitments" variant="quiet" onPress={onBack} /><Title>Commitment detail</Title>
    <Button title="Refresh commitment" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} /><Feedback error={data.error} busy={data.busy} />
    {row && other && <><Card><PersonRow name={other.display_name} role={"You are the " + commitmentRole(row,data.userId)!.toLowerCase()} />
      <StatusChip label={statusLabels[row.status]} /><Body>{proposalContext(row,data.userId)}</Body><Body>{formatMoney(row.principal_amount_minor,row.currency)}</Body>
      <Body>{row.type === "IOU" ? "IOU" : "Peer loan"}</Body><Body>{row.description || "No description"}</Body><Body supporting>Fides records the commitment. Money moves outside Fides.</Body></Card>
      {data.data?.terms && <TermsView terms={data.data.terms} />}
      {data.data?.installments && <Card title="Installment schedule">{data.data.installments.map(item => <View key={item.id} style={styles.form}>
        <Body>Installment {item.sequence_no} · {item.due_date}</Body><StatusChip label={item.status.replaceAll("_"," ")} />
        <Body>Principal: {formatMoney(item.principal_amount_minor,item.currency)}</Body><Body>Interest: {formatMoney(item.interest_amount_minor,item.currency)}</Body><Body>Total due: {formatMoney(item.total_due_minor,item.currency)}</Body>
      </View>)}</Card>}
      {proposalActions(row,data.userId).map(action => {const pending = data.pending(action); return <Button key={action}
        title={pending ? "Retry same " + action : {confirm:"Confirm commitment",reject:"Reject proposal",cancel:"Cancel proposal"}[action]}
        disabled={data.busy || data.actionBlocked(action) || !data.data?.terms || !!pending?.blocked || !!pending?.needsReconcile} onPress={() => setConfirmation(action)} />;})}
      {copy && <Modal transparent visible animationType="fade" onRequestClose={() => setConfirmation(null)}><View style={styles.overlay}><View accessibilityViewIsModal style={styles.dialog}>
        <Title>{copy.title}</Title><Body>{copy.body}</Body><Button title="Go back" variant="quiet" onPress={() => setConfirmation(null)} /><Button title={copy.button}
          onPress={() => {const action = confirmation!; setConfirmation(null); void data.action(action);}} /></View></View></Modal>}
    </>}
  </Screen>;
}
const styles = StyleSheet.create({
  form: {gap:spacing.lg}, choice: {minHeight:controls.button,padding:spacing.md,borderWidth:1,borderColor:colors.border,borderRadius:radii.control},
  selected: {borderColor:colors.brand.signal}, overlay: {flex:1,backgroundColor:colors.canvas,justifyContent:"center",padding:spacing.lg},
  dialog: {backgroundColor:colors.surface,borderRadius:radii.card,borderWidth:1,borderColor:colors.border,padding:spacing.lg,gap:spacing.lg,width:"100%",maxWidth:640,alignSelf:"center"},
});
