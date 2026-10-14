import { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { ProtectedModal as Modal } from "../../navigation/ProtectedModal";
import { colors, radii, spacing } from "@fides/shared/tokens/index";
import type { Repayment, RepaymentRequest, DecisionRequest } from "@fides/shared/api/repayments";
import { formatMoney } from "@fides/shared/domain/money";
import { canReport, canDecide, labels, semantics, reportBody, decisionBody, decisionCopy, type DecisionAction } from "@fides/shared/repayments/model";
import { statusLabels } from "@fides/shared/commitments/model";
import { dateOnlyLabel } from "@fides/shared/dashboard/due-presentation";
import { Amount, Body, Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, Screen, StatusChip, TextField, Title } from "../../components/ui";
import { useRepayments } from "./useRepayments";
import { useAuth } from "../auth/useAuth";
import { notificationTimestamp as formatTimestamp } from "@fides/shared/notifications/presentation";
function Feedback({error,busy}:{error:string|null;busy:boolean}) {return <>{error && <ErrorState message={error}/>}{busy && <LoadingState message="Loading the authoritative repayment record…"/>}</>;}
function Facts({row}:{row:Repayment}) {const {state}=useAuth();if(state.status!=="authenticated")return null;return <><PersonRow name={row.reported_by.display_name} role="Reported by"/><Amount minor={row.amount_minor} currency={row.currency} size="card"/><StatusChip label={labels[row.status]} status={semantics[row.status]}/>
  <Body>Payment date: {dateOnlyLabel(row.payment_date)}</Body><Body supporting>Reported at: {formatTimestamp(row.reported_at,state.user.timezone)}</Body><Body>Note: {row.note || "No note"}</Body>
  {row.status === "PENDING_VERIFICATION" && <Body supporting>Reported, not yet verified. The other participant still needs to verify or dispute this repayment.</Body>}</>;}
export function RepaymentsSection({id,onReport,onDetail}:{id:string;onReport:()=>void;onDetail:(id:string)=>void}) {
 const data=useRepayments(id);
 return <View style={styles.stack}><Title>Repayments</Title><Feedback error={data.error} busy={data.busy}/><Button title="Refresh repayments" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/>
   {data.fresh && data.data && canReport(data.data.parent,data.userId) && <Button title="Report repayment" onPress={onReport}/>}
   {data.data?.rows.length===0 && <EmptyState title="No repayments reported" message="Reported repayments will appear here as separate records."/>}
   {data.data?.rows.map(row=><Card key={row.id}><Facts row={row}/><Button title={"View repayment reported by "+row.reported_by.display_name+" · "+formatMoney(row.amount_minor,row.currency)+" · "+dateOnlyLabel(row.payment_date)} variant="quiet" onPress={()=>onDetail(row.id)}/></Card>)}
 </View>;
}
export function ReportRepayment({id,onBack,onDetail}:{id:string;onBack:()=>void;onDetail:(id:string)=>void}) {
 const data=useRepayments(id),[form,setForm]=useState({amount:"",date:"",note:""}),[review,setReview]=useState<RepaymentRequest|null>(null),[validation,setValidation]=useState<string|null>(null);
 const pending=data.pending("report"),body=pending ? JSON.parse(pending.payload) as RepaymentRequest : review,parent=data.data?.parent,eligible=!!parent && data.fresh && canReport(parent,data.userId);
 return <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS==="ios"?"padding":undefined}><Screen><Button title="Back to commitment" variant="quiet" onPress={onBack}/><Title>Report repayment</Title><Feedback error={data.error} busy={data.busy}/>{validation && <ErrorState message={validation}/>}
   <Button title="Refresh record" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/>{parent && <Body>Commitment currency: {parent.currency} · {statusLabels[parent.status]}</Body>}
   {parent && data.fresh && !canReport(parent,data.userId) && <ErrorState message="This commitment does not currently allow repayment reporting."/>}
   {body ? <><Card title="Review repayment"><Amount minor={body.amount_minor} currency={body.currency} size="card"/><Body>Payment date: {dateOnlyLabel(body.payment_date)}</Body><Body>Note: {body.note || "No note"}</Body><Body>You are reporting this repayment.</Body><Body>It will remain pending until the other participant verifies or disputes it.</Body><Body supporting>Fides records this repayment. Money moves outside Fides.</Body></Card>
     {pending && <Body>The earlier attempt may have completed. Its original key and payload are retained; refresh before explicitly retrying the same request.</Body>}
     {!pending && <Button title="Edit report" variant="quiet" disabled={data.busy} onPress={()=>setReview(null)}/>}
     <Button title={pending ? "Retry same report" : "Report repayment"} disabled={data.busy || !eligible || !!pending?.blocked || !!pending?.needsReconcile} onPress={()=>{void data.report(body).then(row=>{if(row)onDetail(row.id);});}}/></> : parent && <View style={styles.stack}>
     <TextField label={"Amount ("+parent.currency+")"} keyboardType="decimal-pad" editable={!data.busy && eligible} value={form.amount} hint="Positive amount, up to two fractional digits. Currency is locked to the commitment." onChangeText={amount=>setForm({...form,amount})}/>
     <TextField label="Payment date" editable={!data.busy && eligible} autoCapitalize="none" value={form.date} hint="YYYY-MM-DD, date only. The server checks your account timezone." onChangeText={date=>setForm({...form,date})}/>
     <TextField label="Note (optional)" editable={!data.busy && eligible} multiline value={form.note} hint={Array.from(form.note.trim()).length+"/500 characters after trimming"} onChangeText={note=>setForm({...form,note})}/>
     <Button title="Review repayment" disabled={data.busy || !eligible} onPress={()=>{try{setReview(reportBody(form,parent));setValidation(null);}catch(error){setValidation(error instanceof Error ? error.message : "Check the report fields.");}}}/>
   </View>}
 </Screen></KeyboardAvoidingView>;
}
function Confirmation({action,onCancel,onSubmit}:{action:DecisionAction;onCancel:()=>void;onSubmit:(body:DecisionRequest)=>void}) {
 const [note,setNote]=useState(""),[error,setError]=useState<string|null>(null),copy=decisionCopy(action);
 return <Modal transparent visible animationType="fade" onRequestClose={onCancel}><KeyboardAvoidingView style={styles.overlay} behavior={Platform.OS==="ios"?"padding":undefined}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.dialogScroll}><View accessibilityViewIsModal style={styles.dialog}><Title>{copy.title}</Title><Body>{copy.body}</Body><Body supporting>{copy.support}</Body>
   <TextField label="Note (optional)" multiline value={note} hint={copy.hint+" "+Array.from(note.trim()).length+"/500"} onChangeText={setNote}/>{error && <ErrorState message={error}/>}
   <Button title="Go back" variant="quiet" onPress={onCancel}/><Button title={copy.button} variant={action === "dispute" ? "secondary" : "primary"} onPress={()=>{try{onSubmit(decisionBody(note));}catch(error){setError(error instanceof Error ? error.message : "Check the note.");}}}/>
 </View></ScrollView></KeyboardAvoidingView></Modal>;
}
export function RepaymentDetail({id,onBack}:{id:string;onBack:()=>void}) {
 const data=useRepayments(undefined,id),[confirmation,setConfirmation]=useState<DecisionAction|null>(null),row=data.data?.detail,parent=data.data?.parent;
 const {state}=useAuth();
 const eligible=!!row && !!parent && data.fresh && canDecide(row,parent,data.userId);
 if(state.status!=="authenticated")return null;
 return <Screen><Button title="Back to commitment" variant="quiet" onPress={onBack}/><Title>Repayment detail</Title><Button title="Refresh repayment and history" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/><Feedback error={data.error} busy={data.busy}/>
   {row && <><Card><Facts row={row}/></Card>{parent && <Body>Commitment: {statusLabels[parent.status]}</Body>}
     {row.status === "PENDING_VERIFICATION" && row.reported_by.id === data.userId && <Body>You reported this repayment. Only the other participant can verify or dispute it.</Body>}
     {eligible && (["verify","dispute"] as const).map(action=>{const pending=data.pending(action);return <Button key={action} title={pending ? "Retry same "+action : decisionCopy(action).button} variant={action === "dispute" ? "secondary" : "primary"} disabled={data.busy || data.actionBlocked(action) || !!pending?.blocked || !!pending?.needsReconcile}
       onPress={()=>{if(pending)void data.decide(action,JSON.parse(pending.payload));else setConfirmation(action);}}/>;})}
     {(["verify","dispute"] as const).some(action=>data.pending(action)) && <Body>An earlier decision may have completed. Refresh the record and history before explicitly retrying the original decision. The opposite action remains unavailable.</Body>}
     <Card title="Verification history">{data.data?.history ? data.data.history.length ? data.data.history.map(entry=><View style={styles.stack} key={entry.id}><PersonRow name={entry.decided_by.display_name} role="Decision by"/><StatusChip label={labels[entry.decision]} status={semantics[entry.decision]}/><Body supporting>{formatTimestamp(entry.decided_at,state.user.timezone)}</Body><Body>{entry.decision_note || "No decision note"}</Body></View>) : <Body>No verification or dispute decision yet.</Body> : <Body>Refresh to load current history.</Body>}</Card>
     {confirmation && <Confirmation action={confirmation} onCancel={()=>setConfirmation(null)} onSubmit={body=>{const action=confirmation;setConfirmation(null);void data.decide(action,body);}}/>}
   </>}
 </Screen>;
}
const styles=StyleSheet.create({flex:{flex:1},dialogScroll:{flexGrow:1,justifyContent:"center"},stack:{gap:spacing.lg},overlay:{flex:1,backgroundColor:colors.canvas,justifyContent:"center",padding:spacing.lg},dialog:{backgroundColor:colors.surface,borderRadius:radii.card,borderWidth:1,borderColor:colors.border,padding:spacing.lg,gap:spacing.lg,width:"100%",maxWidth:640,alignSelf:"center"}});
