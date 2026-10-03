import { isReminderNotification, type Notification, type NotificationType } from "../api/notifications";

const workflowCopy:Partial<Record<NotificationType,string>>={
 COMMITMENT_PROPOSED:"proposed a commitment.",
 COMMITMENT_CONFIRMED:"confirmed a commitment.",
 COMMITMENT_REJECTED:"rejected a commitment proposal.",
 COMMITMENT_CANCELLED:"cancelled a commitment proposal.",
 REPAYMENT_REPORTED:"reported a repayment.",
 REPAYMENT_VERIFIED:"verified a repayment.",
 REPAYMENT_DISPUTED:"disputed a repayment.",
 EXTENSION_REQUESTED:"requested a due-date extension.",
 EXTENSION_ACCEPTED:"accepted a due-date extension.",
 EXTENSION_REJECTED:"rejected a due-date extension.",
 MUTUAL_CLOSURE_REQUESTED:"requested mutual closure.",
 MUTUAL_CLOSURE_ACCEPTED:"accepted mutual closure.",
 MUTUAL_CLOSURE_REJECTED:"rejected mutual closure.",
};
const reminderCopy={
 UPCOMING_DUE:"Payment due soon",
 DUE_TODAY:"Payment due today",
 OVERDUE:"Payment overdue",
} as const;

export function notificationText(r:Notification){
 if(isReminderNotification(r.type))return reminderCopy[r.type];
 if(!r.actor)throw new Error("Workflow notification requires an actor.");
 return r.actor.display_name+" "+workflowCopy[r.type];
}
export function notificationTarget(r:Notification){
 return r.type.startsWith("REPAYMENT_")&&r.repayment_id
  ?{page:"repayment" as const,id:r.repayment_id,parent:r.commitment_id}
  :{page:"commitment" as const,id:r.commitment_id,extension:r.type.startsWith("EXTENSION_")};
}
export function appendNotifications(previous:Notification[],next:Notification[]){
 const ids=new Set(previous.map(r=>r.id));
 return [...previous,...next.filter(r=>!ids.has(r.id))];
}
