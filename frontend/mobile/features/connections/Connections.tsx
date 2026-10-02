import { useState } from "react";
import { Modal, StyleSheet, View } from "react-native";
import { colors, radii, spacing } from "@fides/shared/tokens/index";
import type { Connection } from "@fides/shared/api/connections";
import { actionLabel, availableConnectionActions, confirmation, connectionSections, otherParticipant,
  relationshipContext, statusLabel, type ConnectionAction } from "@fides/shared/connections/model";
import { Body, Button, Card, EmptyState, ErrorState, LoadingState, PersonRow, Screen, StatusChip, TextField, Title } from "../../components/ui";
import { useConnections } from "./useConnections";
type Destination = { page: "list" } | { page: "new" } | { page: "detail"; id: string };
export function Connections() {
  const [destination, setDestination] = useState<Destination>({ page: "list" });
  const back = () => setDestination({ page: "list" });
  return destination.page === "new" ? <NewConnection onBack={back} onDetail={id => setDestination({ page: "detail", id })} /> :
    destination.page === "detail" ? <ConnectionDetail key={destination.id} id={destination.id} onBack={back} onNew={() => setDestination({ page: "new" })} /> :
    <ConnectionsList onNew={() => setDestination({ page: "new" })} onDetail={id => setDestination({ page: "detail", id })} />;
}
function Feedback({ error, busy }: { error: string | null; busy: boolean }) {
  return <>{error && <ErrorState message={error} />}{busy && <LoadingState message="Updating from Fides…" />}</>;
}
function ConnectionsList({ onNew, onDetail }: { onNew: () => void; onDetail: (id: string) => void }) {
  const data = useConnections();
  return <Screen><Title>Connections</Title><Body>Connections let you create shared commitments later.</Body>
    <Button title="Add connection" onPress={onNew} /><Button title="Refresh connections" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} />
    <Feedback error={data.error} busy={data.busy} />
    {data.rows?.length === 0 && <EmptyState title="No connections yet" message="Connect with someone you know to start keeping shared commitments organized." />}
    {data.rows && connectionSections(data.rows, data.userId).map(section => <Card key={section.title} title={section.title}>
      {section.rows.map(row => <View key={row.id} style={styles.row}>
        <PersonRow name={otherParticipant(row, data.userId)!.display_name} role={relationshipContext(row, data.userId)} />
        <StatusChip label={statusLabel[row.status]} />
        <Button title={"View connection with " + otherParticipant(row, data.userId)!.display_name} variant="quiet" onPress={() => onDetail(row.id)} />
      </View>)}
    </Card>)}
  </Screen>;
}
function NewConnection({ onBack, onDetail }: { onBack: () => void; onDetail: (id: string) => void }) {
  const data = useConnections(); const [phone, setPhone] = useState("");
  return <Screen><Button title="Back to Connections" variant="quiet" onPress={onBack} /><Title>Add connection</Title>
    <TextField label="Phone number" hint="Use international format, beginning with +." keyboardType="phone-pad"
      autoComplete="off" autoCorrect={false} editable={!data.busy} value={phone} onChangeText={setPhone} />
    <Body supporting>Enter the number of someone you know. Fides does not search your contacts.</Body>
    <Feedback error={data.error} busy={data.busy} />
    <Button title="Send connection request" disabled={data.busy || data.uncertain || !phone.trim()} onPress={() => {
      void data.create(phone).then(row => { if (row) { setPhone(""); onDetail(row.id); } });
    }} />
    {data.uncertain && <Button title="Refresh before retrying" variant="quiet" onPress={() => void data.refresh()} />}
  </Screen>;
}
function ConnectionDetail({ id, onBack, onNew }: { id: string; onBack: () => void; onNew: () => void }) {
  const data = useConnections(id); const [pending, setPending] = useState<ConnectionAction | null>(null);
  const row = data.detail; const other = row && otherParticipant(row, data.userId);
  return <Screen><Button title="Back to Connections" variant="quiet" onPress={onBack} /><Title>Connection detail</Title>
    <Button title="Refresh connection" variant="quiet" disabled={data.busy} onPress={() => void data.refresh()} />
    <Feedback error={data.error} busy={data.busy} />
    {row && other && <Card><PersonRow name={other.display_name} role={relationshipContext(row, data.userId)} />
      <StatusChip label={statusLabel[row.status]} />
      <Body supporting>Created: {new Date(row.created_at).toLocaleString()}</Body>
      <Body supporting>Updated: {new Date(row.updated_at).toLocaleString()}</Body>
      {row.status === "BLOCKED" && <Body>This connection is blocked. Fides does not currently provide an unblock action.</Body>}
      {row.status === "REMOVED" && <><Body>This connection is removed. To send a new request, enter the phone number again.</Body>
        <Button title="Send new request" variant="secondary" onPress={onNew} /></>}
      {availableConnectionActions(row, data.userId).map(action => <Button key={action} title={actionLabel(action, row)}
        variant={action === "accept" ? "primary" : "secondary"} disabled={data.busy || data.uncertain} onPress={() => setPending(action)} />)}
      {pending && <Confirm action={pending} row={row} onCancel={() => setPending(null)}
        onConfirm={() => { setPending(null); void data.action(pending, row); }} />}
    </Card>}
  </Screen>;
}
function Confirm({ action, row, onCancel, onConfirm }: {
  action: ConnectionAction; row: Connection; onCancel: () => void; onConfirm: () => void;
}) {
  const copy = confirmation(action, row);
  return <Modal transparent visible animationType="fade" onRequestClose={onCancel}>
    <View style={styles.overlay}><View accessibilityViewIsModal style={styles.dialog}>
      <Title>{copy.title}</Title><Body>{copy.body}</Body>
      <Button title="Cancel" variant="quiet" onPress={onCancel} />
      <Button title={copy.button} variant={action === "accept" ? "primary" : "secondary"} onPress={onConfirm} />
    </View></View>
  </Modal>;
}
const styles = StyleSheet.create({
  row: { gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderColor: colors.border },
  overlay: { flex: 1, backgroundColor: colors.canvas, justifyContent: "center", padding: spacing.lg },
  dialog: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg, gap: spacing.lg, width: "100%", maxWidth: 640, alignSelf: "center" },
});
