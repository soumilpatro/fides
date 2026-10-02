import { useState } from "react";
import { KeyboardAvoidingView,Platform } from "react-native";
import { Body,Button,Card,ErrorState,Screen,TextField,Title } from "../../components/ui";
import { useProfile } from "./useProfile";
export function Profile({onCommitments}:{onCommitments:()=>void}){
 const data=useProfile(),[editing,setEditing]=useState(false),[name,setName]=useState(""),[timezone,setTimezone]=useState(""),[deactivating,setDeactivating]=useState(false),[typed,setTyped]=useState(""),[validation,setValidation]=useState<string|null>(null);
 if(!data.user)return null;const user=data.user;
 if(deactivating)return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==="ios"?"padding":undefined}><Screen>
 <Button title="Go back" variant="quiet" disabled={data.busy} onPress={()=>setDeactivating(false)}/><Title>Deactivate account?</Title>
 <Body>Your account will be deactivated. This action is only available when Fides has no unresolved commitments preventing deactivation.</Body>
 <TextField label="Type DEACTIVATE to continue." autoCapitalize="none" autoCorrect={false} value={typed} editable={!data.busy} onChangeText={setTyped}/>
 {data.error&&<ErrorState message={data.error}/>} {data.blocked&&<Button title="Back to commitments" variant="secondary" onPress={onCommitments}/>}
 <Button title={data.busy?"Deactivating…":"Deactivate account"} variant="destructive" disabled={data.busy||typed!=="DEACTIVATE"} onPress={()=>void data.deactivate(typed)}/>
 </Screen></KeyboardAvoidingView>;
 return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==="ios"?"padding":undefined}><Screen><Title>Profile / Settings</Title><Card title="Profile">
 <Body>Display name: {user.display_name}</Body><Body>Phone (read-only): {user.phone_e164??"Unavailable"}</Body><Body>Timezone: {user.timezone}</Body>
 {editing?<><TextField label="Display name" value={name} editable={!data.busy} onChangeText={setName}/>
 <TextField label="Timezone" hint="Valid IANA identifier. Your device timezone never replaces this automatically." value={timezone} autoCapitalize="none" editable={!data.busy} onChangeText={setTimezone}/>
 <Button title={data.busy?"Saving…":"Save profile"} disabled={data.busy||name===user.display_name&&timezone===user.timezone} onPress={()=>{try{new Intl.DateTimeFormat("en",{timeZone:timezone});if(!name.trim())throw new Error("Enter a display name.");setValidation(null);void data.save({...(name!==user.display_name?{display_name:name}:{}),...(timezone!==user.timezone?{timezone}:{})}).then(ok=>{if(ok)setEditing(false);});}catch{setValidation("Enter a display name and a valid IANA timezone.");}}}/>
 <Button title="Cancel edit" variant="quiet" disabled={data.busy} onPress={()=>setEditing(false)}/></>:<Button title="Edit profile" variant="secondary" disabled={data.busy} onPress={()=>{setName(user.display_name);setTimezone(user.timezone);setValidation(null);setEditing(true);}}/>}
 {validation&&<ErrorState message={validation}/>} {data.saved&&<Body>Profile saved.</Body>}{data.error&&<ErrorState message={data.error}/>}<Button title="Refresh profile" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/></Card>
 <Card title="Account"><Button title="Log out" variant="secondary" disabled={data.busy} onPress={()=>void data.logout()}/><Button title="Deactivate account" variant="destructive" disabled={data.busy} onPress={()=>{setTyped("");setDeactivating(true);}}/></Card>
 </Screen></KeyboardAvoidingView>;
}
