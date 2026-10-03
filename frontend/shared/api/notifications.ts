import { createApiClient } from "./request";
import { boundedFetch } from "./dashboard";
import { array, object, text, uuid, stamp, person, identifier, invalidResponse } from "./f6-values";
import type { Person } from "./commitments";

export const reminderNotificationTypes=["UPCOMING_DUE","DUE_TODAY","OVERDUE"] as const;
export type ReminderNotificationType=typeof reminderNotificationTypes[number];

export const notificationTypes=[
 "COMMITMENT_PROPOSED","COMMITMENT_CONFIRMED","COMMITMENT_REJECTED","COMMITMENT_CANCELLED",
 "REPAYMENT_REPORTED","REPAYMENT_VERIFIED","REPAYMENT_DISPUTED",
 "EXTENSION_REQUESTED","EXTENSION_ACCEPTED","EXTENSION_REJECTED",
 "MUTUAL_CLOSURE_REQUESTED","MUTUAL_CLOSURE_ACCEPTED","MUTUAL_CLOSURE_REJECTED",
 ...reminderNotificationTypes,
] as const;

export type NotificationType=typeof notificationTypes[number];
export interface Notification {
 id:string;
 type:NotificationType;
 actor:Person|null;
 commitment_id:string;
 repayment_id:string|null;
 extension_request_id:string|null;
 created_at:string;
 read_at:string|null;
}
export interface NotificationPage {items:Notification[];next_cursor:string|null}

export const isReminderNotification=(type:NotificationType):type is ReminderNotificationType=>
 reminderNotificationTypes.includes(type as ReminderNotificationType);

export function notificationResponse(v:unknown):Notification {
 const r=object(v),type=text(r.type) as NotificationType;if(!notificationTypes.includes(type))invalidResponse();
 const reminder=isReminderNotification(type);
 const actor=r.actor===null?null:person(r.actor);
 if(reminder!==(actor===null))invalidResponse();
 const result={
  id:uuid(r.id),type,actor,commitment_id:uuid(r.commitment_id),
  repayment_id:r.repayment_id===null?null:uuid(r.repayment_id),
  extension_request_id:r.extension_request_id===null?null:uuid(r.extension_request_id),
  created_at:stamp(r.created_at),read_at:r.read_at===null?null:stamp(r.read_at),
 };
 if(type.startsWith("REPAYMENT_")?!result.repayment_id:result.repayment_id!==null)invalidResponse();
 if(type.startsWith("EXTENSION_")?!result.extension_request_id:result.extension_request_id!==null)invalidResponse();
 if(reminder&&(result.repayment_id!==null||result.extension_request_id!==null))invalidResponse();
 if(result.read_at&&Date.parse(result.read_at)<Date.parse(result.created_at))invalidResponse();
 return result;
}
export function createNotificationsApi(config:Parameters<typeof createApiClient>[0]){
 const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)});
 return {
  listNotifications:async(options:{limit?:number;cursor?:string}={}):Promise<NotificationPage>=>{
   const limit=options.limit??50;if(!Number.isInteger(limit)||limit<1||limit>100)throw new Error("Invalid page size.");
   if(options.cursor!==undefined&&(!options.cursor.length||options.cursor.length>512||/[\u0000-\u001f\u007f]/.test(options.cursor)))throw new Error("Invalid cursor.");
   const query=new URLSearchParams({limit:String(limit)});if(options.cursor!==undefined)query.set("cursor",options.cursor);
   const r=object(await request("/notifications?"+query)),cursor=r.next_cursor===null?null:text(r.next_cursor);if(cursor!==null&&(!cursor.length||cursor.length>512))invalidResponse();
   return {items:array(r.items).map(notificationResponse),next_cursor:cursor};
  },
  markRead:async(id:string)=>{const result=notificationResponse(await request("/notifications/"+identifier(id)+"/read",{method:"POST",body:{}}));if(result.id!==id||!result.read_at)invalidResponse();return result;},
 };
}
export type NotificationsApi=ReturnType<typeof createNotificationsApi>;
