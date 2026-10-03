import { createApiClient } from "./request";
import { boundedFetch } from "./dashboard";
import { object, invalidResponse } from "./f6-values";

export interface NotificationPreferences {
  due_reminders_enabled:boolean;
  overdue_reminders_enabled:boolean;
}

export function notificationPreferencesResponse(value:unknown):NotificationPreferences {
  const row=object(value);
  const dueRemindersEnabled=row.due_reminders_enabled,overdueRemindersEnabled=row.overdue_reminders_enabled;
  if(typeof dueRemindersEnabled!=="boolean"||typeof overdueRemindersEnabled!=="boolean")invalidResponse();
  return {
    due_reminders_enabled:dueRemindersEnabled as boolean,
    overdue_reminders_enabled:overdueRemindersEnabled as boolean,
  };
}

export function createNotificationPreferencesApi(config:Parameters<typeof createApiClient>[0]){
  const request=createApiClient({...config,fetcher:boundedFetch(config.fetcher??fetch)});
  return {
    getPreferences:async()=>notificationPreferencesResponse(await request("/notification-preferences")),
    updatePreferences:async(body:NotificationPreferences)=>notificationPreferencesResponse(await request("/notification-preferences",{method:"POST",body})),
  };
}
export type NotificationPreferencesApi=ReturnType<typeof createNotificationPreferencesApi>;
