"use client";
import { useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { ProfileUpdate } from "@fides/shared/api/profile";
import { useAuth } from "../auth/useAuth";
export function useProfile(){
 const {profile,state,session}=useAuth(),user=state.status==="authenticated"?state.user:null;
 const [busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),[saved,setSaved]=useState(false),[blocked,setBlocked]=useState(false);
 const flight=useRef(false);
 const save=async(body:ProfileUpdate)=>{
  if(flight.current||!user)return false;flight.current=true;setBusy(true);setError(null);setSaved(false);
  try{const result=await profile.updateProfile(body);session.reconcileUser(result);setSaved(true);return true;}
  catch(e){setError(e instanceof ApiError?e.message:"Save could not be confirmed. Refresh your profile before trying again.");if(e instanceof ApiError&&e.status===401)await session.bootstrap();return false;}
  finally{flight.current=false;setBusy(false);}
 };
 const deactivate=async(confirmation:string)=>{
  if(confirmation!=="DEACTIVATE"||flight.current||!user)return false;flight.current=true;setBusy(true);setError(null);setBlocked(false);
  try{await profile.deactivate();await session.clearDeactivated();return true;}
  catch(e){const unresolved=e instanceof ApiError&&e.code==="ACCOUNT_HAS_UNRESOLVED_COMMITMENTS";setBlocked(unresolved);setError(unresolved?"Your account can't be deactivated while unresolved commitments remain.":e instanceof ApiError?e.message:"Deactivation could not be confirmed. Refresh your session before trying again.");return false;}
  finally{flight.current=false;setBusy(false);}
 };
 return {user,busy,error,saved,blocked,save,deactivate,refresh:()=>session.bootstrap(),logout:()=>session.logout()};
}
