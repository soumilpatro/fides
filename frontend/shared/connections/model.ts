import type { Connection } from "../api/connections";
import { ApiError } from "../api/errors";
export type ConnectionAction = "accept" | "reject" | "block" | "remove";
export function connectionRole(row: Connection, userId: string) {
  const requester = row.requester.id === userId;
  const recipient = row.recipient.id === userId;
  return requester === recipient ? null : requester ? "requester" : "recipient";
}
export function otherParticipant(row: Connection, userId: string) {
  const role = connectionRole(row, userId);
  return role === null ? null : role === "requester" ? row.recipient : row.requester;
}
export function availableConnectionActions(row: Connection, userId: string): ConnectionAction[] {
  const role = connectionRole(row, userId);
  if (!role) return [];
  if (row.status === "PENDING") return role === "recipient" ? ["accept", "reject", "block"] : ["remove", "block"];
  return row.status === "ACCEPTED" ? ["remove", "block"] : [];
}
export const statusLabel = { PENDING: "Pending", ACCEPTED: "Connected", BLOCKED: "Blocked", REMOVED: "Removed" };
export function relationshipContext(row: Connection, userId: string) {
  const role = connectionRole(row, userId);
  return row.status === "PENDING" ? role === "recipient" ? "Incoming request" : "Sent request" : statusLabel[row.status];
}
export const sections = ["Incoming requests", "Sent requests", "Connections", "Blocked", "Removed"] as const;
export function connectionSections(rows: Connection[], userId: string) {
  return sections.map(title => ({ title, rows: rows.filter(row => {
    const role = connectionRole(row, userId);
    if (!role) return false;
    return (row.status === "PENDING" ? role === "recipient" ? "Incoming requests" : "Sent requests" :
      row.status === "ACCEPTED" ? "Connections" : statusLabel[row.status]) === title;
  }) })).filter(section => section.rows.length);
}
export function actionLabel(action: ConnectionAction, row: Connection) {
  return { accept: "Accept", reject: "Decline", block: "Block", remove: row.status === "PENDING" ? "Cancel request" : "Remove connection" }[action];
}
export function confirmation(action: ConnectionAction, row: Connection) {
  if (action === "block") return { title: "Block this connection?", body: "This connection will be blocked. Fides does not currently provide an unblock action.", button: "Block connection" };
  if (action === "remove" && row.status === "ACCEPTED") return { title: "Remove connection?", body: "The connection will be removed. Existing financial records are not deleted.", button: "Remove connection" };
  const label = actionLabel(action, row);
  return { title: action === "remove" ? label + "?" : label + " request?", body: action === "accept" ? "The connection request will be accepted." :
    action === "reject" ? "The connection request will be declined." : "The connection request will be cancelled.", button: label };
}
export function connectionError(error: unknown, creating = false) {
  if (!(error instanceof ApiError)) return "Unable to confirm the result. Refresh before trying again.";
  if (error.code === "NOT_FOUND") return creating ? "We couldn't send a connection request to that number." : "This connection is unavailable.";
  if (error.code === "CONFLICT") return "A pending, connected, or blocked relationship already exists. Refresh to see its current state.";
  if (error.code === "INVALID_STATE") return "This connection has changed. Refresh to see its current state.";
  if (error.code === "FORBIDDEN") return "This action is not available to you.";
  if (error.code === "VALIDATION_ERROR") return "Check the international phone number. You cannot connect with yourself.";
  if (error.status === 401) return "Your session needs attention. Please log in again.";
  return "Unable to confirm the result. Refresh before trying again.";
}
