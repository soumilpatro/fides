import { useState } from "react";
import { KeyboardAvoidingView, Modal, Platform, StyleSheet, Text, View } from "react-native";
import { colors,radii,spacing } from "@fides/shared/tokens/index";
import type { Extension, ExtensionRequest } from "@fides/shared/api/extensions";
import { canRequestExtension, extensionActions, extensionBody } from "@fides/shared/extensions/model";
import { Body,Button,Card,EmptyState,ErrorState,LoadingState,Screen,StatusChip,TextField,Title } from "../../components/ui";
import { useExtensions } from "./useExtensions";
export function ExtensionsSection({id,onRequest,onChanged}:{id:string;onRequest:()=>void;onChanged:()=>void}){
 const data=useExtensions(id),[confirmation,setConfirmation]=useState<{row:Extension;action:"accept"|"reject"}|null>(null);
 return <View style={styles.stack}><Text accessibilityRole="header" style={styles.section}>Due-date extension</Text><Button title="Refresh extensions" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/>
 {data.busy&&<LoadingState message="Loading due-date requests…"/>}{data.error&&<ErrorState message={data.error}/>}
 {data.data&&<>{canRequestExtension(data.data.parent,data.data.terms,data.data.rows)&&!data.pending("create")&&<Button title="Request extension" onPress={onRequest}/>}
 {data.pending("create")&&<Button title="Review earlier extension request" variant="secondary" onPress={onRequest}/>}
 {!data.data.rows.length&&<EmptyState title="No extension requests" message="A due-date change needs the other participant's acceptance."/>}
 {data.data.rows.map(row=><Card key={row.id}><StatusChip label={row.status==="REQUESTED"&&row.requested_by.id===data.user?"Awaiting response":row.status==="REQUESTED"?"Requested":row.status.charAt(0)+row.status.slice(1).toLowerCase()} status={row.status==="REQUESTED"?"PENDING":undefined}/>
 <Body>Requested by {row.requested_by.display_name}</Body><Body>Previous due date: {row.previous_due_date}</Body><Body>{row.status==="ACCEPTED"?"Accepted due date":"Requested due date"}: {row.requested_due_date}</Body>
 {row.reason&&<Body>{row.reason}</Body>}{row.decided_by&&<Body supporting>{row.decided_by.display_name} · {row.decided_at}</Body>}
 {extensionActions(row,data.user,data.data!.parent,data.data!.terms).map(action=>{
 const pending=data.pending(action,row.id),opposite=data.pending(action==="accept"?"reject":"accept",row.id);
 return <Button key={action} title={pending?"Retry same "+action:action==="accept"?"Accept extension":"Reject extension"} disabled={data.busy||!!opposite||!!pending?.blocked||!!pending?.needsReconcile} onPress={()=>setConfirmation({row,action})}/>;
 })}</Card>)}</>}
 {confirmation&&<Modal transparent visible animationType="none" onRequestClose={()=>setConfirmation(null)}><View style={styles.overlay}><View accessibilityViewIsModal style={styles.sheet}>
 <Title>{confirmation.action==="accept"?"Accept this extension?":"Reject this extension?"}</Title>
 <Body>{confirmation.action==="accept"?"The commitment due date will change from "+confirmation.row.previous_due_date+" to "+confirmation.row.requested_due_date+".":"The current due date will remain unchanged."}</Body>
 <Button title="Go back" variant="quiet" onPress={()=>setConfirmation(null)}/><Button title={confirmation.action==="accept"?"Accept extension":"Reject extension"} onPress={()=>{const {row,action}=confirmation;setConfirmation(null);void data.decide(row,action).then(r=>{if(r)onChanged();});}}/>
 </View></View></Modal>}</View>;
}
export function NewExtension({id,onBack}:{id:string;onBack:()=>void}){
 const data=useExtensions(id),[date,setDate]=useState(""),[reason,setReason]=useState(""),[review,setReview]=useState<ExtensionRequest|null>(null),[validation,setValidation]=useState<string|null>(null);
 const pending=data.pending("create"),body=pending?JSON.parse(pending.payload) as ExtensionRequest:review;
 return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==="ios"?"padding":undefined}><Screen><Button title="Back to commitment" variant="quiet" disabled={data.busy} onPress={onBack}/><Title>Request extension</Title>
 <Body>This changes the due date only if the other participant accepts.</Body>{data.busy&&<LoadingState message="Loading current terms…"/>}{data.error&&<ErrorState message={data.error}/>}
 {validation&&<ErrorState message={validation}/>}
 {data.data&&<><Body>Current due date: {data.due??"No deadline"}</Body>
 {body?<><Card title="Review extension"><Body>Requested due date: {body.requested_due_date}</Body><Body>{body.reason??"No reason supplied"}</Body></Card>
 {pending&&<Body>The earlier attempt may have completed. Its original key and payload are retained. Refresh before explicitly retrying.</Body>}
 {!pending&&<Button title="Edit request" variant="quiet" disabled={data.busy} onPress={()=>setReview(null)}/>}
 <Button title={pending?"Retry same request":"Submit extension request"} disabled={data.busy||!!pending?.blocked||!!pending?.needsReconcile} onPress={()=>void data.request(body).then(r=>{if(r)onBack();})}/>
 {pending&&<Button title="Refresh before retrying" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/>}</>:
 canRequestExtension(data.data.parent,data.data.terms,data.data.rows)?<>
 <TextField label="Requested due date" hint="YYYY-MM-DD; later than the current due date." value={date} editable={!data.busy} onChangeText={setDate}/>
 <TextField label="Reason (optional)" multiline value={reason} editable={!data.busy} onChangeText={setReason} hint={Array.from(reason.trim()).length+"/500 characters after trimming"}/>
 <Button title="Review extension" disabled={data.busy} onPress={()=>{try{setReview(extensionBody(date,reason,data.due!));setValidation(null);}catch(e){setValidation(e instanceof Error?e.message:"Check the requested date.");}}}/></>:
 <EmptyState title="Extension unavailable" message="Only an eligible single-date commitment without a pending request can request a due-date extension."/>}</>}
 </Screen></KeyboardAvoidingView>;
}
const styles=StyleSheet.create({section:{fontFamily:"ManropeBold",fontSize:20,lineHeight:28,color:colors.text.primary},stack:{gap:spacing.lg},overlay:{flex:1,justifyContent:"flex-end",backgroundColor:colors.canvas,padding:spacing.lg},sheet:{backgroundColor:colors.surface,borderRadius:radii.card,borderWidth:1,borderColor:colors.border,padding:spacing.lg,gap:spacing.lg,width:"100%",maxWidth:640,alignSelf:"center"}});
