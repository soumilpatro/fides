"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { NotificationPreferences } from "@fides/shared/api/notification-preferences";
import { useAuth } from "../auth/useAuth";

export function useNotificationPreferences(){
  const {notificationPreferences,session}=useAuth();
  const [data,setData]=useState<NotificationPreferences|null>(null);
  const [busy,setBusy]=useState(true);
  const [error,setError]=useState<string|null>(null);
  const [saved,setSaved]=useState(false);
  const flight=useRef(false),mounted=useRef(true);

  const refresh=useCallback(async()=>{
    if(flight.current)return;
    flight.current=true;setBusy(true);setError(null);setSaved(false);
    try{const result=await notificationPreferences.getPreferences();if(mounted.current)setData(result);}
    catch(e){if(mounted.current)setError(e instanceof ApiError?e.message:"Notification preferences could not be loaded.");if(e instanceof ApiError&&e.status===401)await session.bootstrap();}
    finally{flight.current=false;if(mounted.current)setBusy(false);}
  },[notificationPreferences,session]);

  useEffect(()=>{mounted.current=true;void refresh();return()=>{mounted.current=false;};},[refresh]);

  const setPreference=async(field:keyof NotificationPreferences,value:boolean)=>{
    if(flight.current||!data)return false;
    flight.current=true;setBusy(true);setError(null);setSaved(false);
    try{
      const result=await notificationPreferences.updatePreferences({...data,[field]:value});
      if(mounted.current){setData(result);setSaved(true);}return true;
    }catch(e){
      if(mounted.current)setError(e instanceof ApiError?e.message:"Notification preference could not be saved. Your previous server setting is still in effect.");
      if(e instanceof ApiError&&e.status===401)await session.bootstrap();
      return false;
    }finally{flight.current=false;if(mounted.current)setBusy(false);}
  };
  return {data,busy,error,saved,refresh,setPreference};
}
