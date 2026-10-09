import { useState } from "react";
import { KeyboardAvoidingView,Platform,Switch,View } from "react-native";
import { Body,Button,Card,ErrorState,LoadingState,Screen,TextField,Title } from "../../components/ui";
import { useProfile } from "./useProfile";
import { useNotificationPreferences } from "./useNotificationPreferences";
export function Profile({onCommitments}:{onCommitments:()=>void}){
 const data=useProfile(),preferences=useNotificationPreferences(),[editing,setEditing]=useState(false),[name,setName]=useState(""),[timezone,setTimezone]=useState(""),[deactivating,setDeactivating]=useState(false),[typed,setTyped]=useState(""),[validation,setValidation]=useState<string|null>(null);
 if(!data.user)return null;const user=data.user;
 if(deactivating)return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==="ios"?"padding":undefined}><Screen>
 <Button title="Go back" variant="quiet" disabled={data.busy} onPress={()=>{data.clearFeedback();setDeactivating(false);}}/><Title>Deactivate account?</Title>
 <Body>Your account will be deactivated. This action is only available when Fides has no unresolved commitments preventing deactivation.</Body>
 <TextField label="Type DEACTIVATE to continue." autoCapitalize="characters" autoCorrect={false} value={typed} editable={!data.busy} onChangeText={setTyped}/>
 {data.error&&<ErrorState message={data.error}/>} {data.blocked&&<Button title="Back to commitments" variant="secondary" disabled={data.busy} onPress={onCommitments}/>}
 <Button title={data.busy?"Deactivating…":"Deactivate account"} variant="destructive" disabled={data.busy||typed!=="DEACTIVATE"} onPress={()=>void data.deactivate(typed)}/>
 </Screen></KeyboardAvoidingView>;
 return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==="ios"?"padding":undefined}><Screen><Title>Profile / Settings</Title><Card title="Profile">
 <Body>Display name: {user.display_name}</Body><Body>Phone (read-only): {user.phone_e164??"Unavailable"}</Body><Body>Timezone: {user.timezone}</Body>
 {editing?<><TextField label="Display name" value={name} editable={!data.busy} onChangeText={setName}/>
 <TextField label="Timezone" hint="Valid IANA identifier. Your device timezone never replaces this automatically." value={timezone} autoCapitalize="none" editable={!data.busy} onChangeText={setTimezone}/>
 <Button title={data.busy?"Saving…":"Save profile"} disabled={data.busy||name===user.display_name&&timezone===user.timezone} onPress={()=>{try{new Intl.DateTimeFormat("en",{timeZone:timezone});if(!name.trim())throw new Error("Enter a display name.");setValidation(null);void data.save({...(name!==user.display_name?{display_name:name}:{}),...(timezone!==user.timezone?{timezone}:{})}).then(ok=>{if(ok)setEditing(false);});}catch{setValidation("Enter a display name and a valid IANA timezone.");}}}/>
 <Button title="Cancel edit" variant="quiet" disabled={data.busy} onPress={()=>setEditing(false)}/></>:<Button title="Edit profile" variant="secondary" disabled={data.busy} onPress={()=>{data.clearFeedback();setName(user.display_name);setTimezone(user.timezone);setValidation(null);setEditing(true);}}/>}
 {validation&&<ErrorState message={validation}/>} {data.saved&&<View accessibilityLiveRegion="polite"><Body>Profile saved.</Body></View>}{data.error&&<ErrorState message={data.error}/>}<Button title="Refresh profile" variant="quiet" disabled={data.busy} onPress={()=>void data.refresh()}/></Card>
 <Card title="Notification preferences"><Body supporting>Choose whether Fides records due-date reminders in your in-app notifications. Changes are confirmed by the server before the switch changes.</Body>
 {preferences.busy&&!preferences.data&&<LoadingState message="Loading notification preferences…"/>}
 {preferences.data&&<>
 <View accessibilityRole="none"><Body>Upcoming due reminders</Body><Body supporting>Notify me when a payment due date is approaching.</Body><Switch accessibilityLabel="Upcoming due reminders" value={preferences.data.due_reminders_enabled} disabled={preferences.busy} onValueChange={value=>void preferences.setPreference("due_reminders_enabled",value)}/></View>
 <View accessibilityRole="none"><Body>Overdue reminders</Body><Body supporting>Notify me when a payment becomes overdue.</Body><Switch accessibilityLabel="Overdue reminders" value={preferences.data.overdue_reminders_enabled} disabled={preferences.busy} onValueChange={value=>void preferences.setPreference("overdue_reminders_enabled",value)}/></View>
 </>}
 {preferences.busy&&preferences.data&&<View accessibilityLiveRegion="polite"><Body>Saving notification preferences…</Body></View>}{preferences.saved&&<View accessibilityLiveRegion="polite"><Body>Notification preferences saved.</Body></View>}{preferences.error&&<><ErrorState message={preferences.error}/><Button title="Retry notification preferences" variant="quiet" disabled={preferences.busy} onPress={()=>void preferences.refresh()}/></>}
 </Card>
 <Card title="Account"><Button title="Log out" variant="secondary" disabled={data.busy} onPress={()=>void data.logout()}/><Button title="Deactivate account" variant="destructive" disabled={data.busy} onPress={()=>{data.clearFeedback();setTyped("");setDeactivating(true);}}/></Card>
 </Screen></KeyboardAvoidingView>;
}
