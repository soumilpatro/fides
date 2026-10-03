import { useState } from "react";
import { Modal, View } from "react-native";
import { formatMoney } from "@fides/shared/domain/money";
import { closureBody, type MutualClosure } from "@fides/shared/api/mutual-closure";
import { canRequestMutualClosure, closureStatusLabel, hasPendingRepayment, mutualClosureActions, verifiedRepayments } from "@fides/shared/mutual-closure/model";
import { Body, Button, Card, EmptyState, ErrorState, LoadingState, StatusChip, TextField, Title } from "../../components/ui";
import { useMutualClosure } from "./useMutualClosure";

export function MutualClosureSection({id,onChanged}:{id:string;onChanged:()=>void}){
 const data=useMutualClosure(id),[requesting,setRequesting]=useState(false),[note,setNote]=useState(""),[validation,setValidation]=useState<string|null>(null),[confirmation,setConfirmation]=useState<{row:MutualClosure;action:"accept"|"reject"|"cancel"}|null>(null);
 const snapshot=data.data,verified=snapshot?verifiedRepayments(snapshot.repayments):[],pendingVerification=snapshot?hasPendingRepayment(snapshot.repayments):false,createPending=data.pending("create");
 return <><Card title="Mutual closure"><Body supporting>Mutual closure is not repayment or unilateral forgiveness. Both people must agree before the commitment can close.</Body><Button title="Refresh mutual closure" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/></Card>
  {data.busy&&!snapshot&&<LoadingState message="Loading mutual-closure status…"/>}{data.error&&<ErrorState message={data.error}/>}
  {snapshot&&<>
   <Card title="Verified repayments">{verified.length===0?<Body>No verified repayments recorded.</Body>:verified.map(row=><Body key={row.id}>{formatMoney(row.amount_minor,row.currency)} · {row.payment_date} · reported by {row.reported_by.display_name}</Body>)}<Body supporting>Only verified repayments are shown here. Fides does not turn a waiver into a repayment entry.</Body></Card>
   {canRequestMutualClosure(snapshot.parent,snapshot.rows)&&!requesting&&!createPending&&<Button title="Request mutual closure" onPress={()=>{setNote("");setValidation(null);setRequesting(true);}}/>}
   {createPending&&!requesting&&<Button title="Review earlier mutual-closure request" variant="secondary" onPress={()=>setRequesting(true)}/>}
   {requesting&&<Card title="Request mutual closure"><Body>Both you and the other person must agree. The remaining verified balance will be waived.</Body><Body supporting>The server will record the authoritative verified outstanding amount when this request is created.</Body>
    <TextField label="Note (optional)" multiline maxLength={500} value={note} editable={!data.busy} onChangeText={value=>{setNote(value);setValidation(null);}} hint={Array.from(note.trim()).length+"/500 characters after trimming"}/>
    {validation&&<ErrorState message={validation}/>}<Button title="Cancel" variant="quiet" disabled={data.busy} onPress={()=>setRequesting(false)}/><Button title={createPending?"Retry same request":"Send request"} disabled={data.busy||!!createPending?.blocked||!!createPending?.needsReconcile} onPress={()=>{try{const body=createPending?JSON.parse(createPending.payload):closureBody(note);setValidation(null);void data.request(body).then(result=>{if(result){setRequesting(false);onChanged();}});}catch(e){setValidation(e instanceof Error?e.message:"Check the note.");}}}/>
    {createPending&&<Body supporting>An earlier attempt may have completed. Refresh before explicitly retrying; the same idempotency key and payload are retained.</Body>}</Card>}
   {!snapshot.rows.length&&!requesting&&<EmptyState title="No mutual-closure requests" message="When eligible, either participant can request closure by mutual agreement."/>}
   {snapshot.rows.map(row=><Card key={row.id}><StatusChip label={closureStatusLabel(row,data.user)} status={row.status==="REQUESTED"?"PENDING":row.status==="ACCEPTED"?"CLOSED":undefined}/><Body>Requested by {row.requested_by.display_name}</Body>
    <Body>Verified outstanding reviewed: {formatMoney(row.outstanding_snapshot_minor,row.currency)}</Body><Body>{row.status==="ACCEPTED"?"Waived amount":"Amount proposed to be waived"}: {formatMoney(row.waived_amount_minor,row.currency)}</Body>
    {row.note&&<Body>{row.note}</Body>}{row.decided_by&&<Body supporting>{row.decided_by.display_name} · {row.decided_at}</Body>}{row.status==="ACCEPTED"&&<Body>Closed by mutual agreement</Body>}
    {row.status==="REQUESTED"&&row.counterparty.id===data.user&&pendingVerification&&<Body>A repayment is pending verification. Resolve it before accepting mutual closure.</Body>}
    {mutualClosureActions(row,data.user).map(action=>{const pending=data.pending(action,row.id),blockedByVerification=action==="accept"&&pendingVerification;return <Button key={action} title={pending?"Retry same "+action:action==="accept"?"Accept":action==="reject"?"Reject":"Cancel request"} variant={action==="cancel"?"secondary":"primary"} disabled={data.busy||blockedByVerification||!!pending?.blocked||!!pending?.needsReconcile} onPress={()=>setConfirmation({row,action})}/>;})}
   </Card>)}
  </>}
  {confirmation&&<Modal transparent visible animationType="fade" onRequestClose={()=>setConfirmation(null)}><View style={{flex:1,justifyContent:"center",padding:24,backgroundColor:"#F7F6F3"}}><View accessibilityViewIsModal style={{padding:24,borderWidth:1,borderColor:"#DFE1E6",borderRadius:16,backgroundColor:"#F7F6F3",gap:16}}>
   <Title>{confirmation.action==="accept"?"Accept mutual closure?":confirmation.action==="reject"?"Reject mutual closure?":"Cancel mutual closure request?"}</Title>
   <Body>{confirmation.action==="accept"?"The commitment will close by mutual agreement and the remaining verified balance shown here will be waived. This is not a repayment.":confirmation.action==="reject"?"The commitment will remain open. No balance will be waived.":"The pending request will be cancelled. The commitment will remain open."}</Body>
   <Button title="Go back" variant="quiet" onPress={()=>setConfirmation(null)}/><Button title={confirmation.action==="accept"?"Accept mutual closure":confirmation.action==="reject"?"Reject request":"Cancel request"} variant={confirmation.action==="cancel"?"secondary":"primary"} onPress={()=>{const {row,action}=confirmation;setConfirmation(null);void data.decide(row,action).then(result=>{if(result)onChanged();});}}/>
  </View></View></Modal>}
 </>;
}
