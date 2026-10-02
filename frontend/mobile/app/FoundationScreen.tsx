import { useState } from "react";
import {
  Amount,
  Body,
  Button,
  Card,
  Divider,
  EmptyState,
  ErrorState,
  LoadingState,
  Micro,
  PersonRow,
  Screen,
  StatusChip,
  TextField,
  Title,
} from "../components/ui";
export function FoundationScreen() {
  const [text, setText] = useState("");
  const [feedback, setFeedback] = useState("Actions affect this preview only.");
  return (
    <Screen>
      <Micro>CLARITY STARTS HERE</Micro>
      <Title>A little structure. A lot of understanding.</Title>
      <Body>
        The building blocks of Fides. Familiar, considered, and clear — on every
        screen.
      </Body>
      <StatusChip label="Foundation preview" />
      <Body supporting>
        Component examples only. No account or financial activity.
      </Body>
      <Card title="Numbers, with room to breathe">
        <Micro>AMOUNT HIERARCHY</Micro>
        <Amount minor={123456} currency="INR" />
        <Body supporting>
          Formatting specimen. Illustrative amount, not a balance.
        </Body>
        <Divider />
        <Micro>CARD AMOUNT</Micro>
        <Amount minor={123456} currency="INR" size="card" />
        <Micro>ROW AMOUNT</Micro>
        <Amount minor={123456} currency="INR" size="row" />
      </Card>
      <Card title="People before numbers">
        <PersonRow name="Sample Person" role="Identity specimen" />
        <Divider />
        <Body>
          Names and roles travel together. A connection never substitutes for
          permission.
        </Body>
      </Card>
      <Card title="A clear next step">
        <TextField
          label="Preview text"
          value={text}
          onChangeText={setText}
          placeholder="Try a little clarity"
          hint="Local preview only. Nothing is submitted or saved."
        />
        <Button
          title="Primary action"
          onPress={() =>
            setFeedback("Primary button activated. No request was sent.")
          }
        />
        <Button
          title="Secondary"
          variant="secondary"
          onPress={() =>
            setFeedback("Secondary button activated. No request was sent.")
          }
        />
        <Button
          title="Reset preview"
          variant="quiet"
          onPress={() => {
            setText("");
            setFeedback("Preview reset.");
          }}
        />
        <Button title="Disabled" disabled onPress={() => {}} />
        <Body supporting>{feedback}</Body>
      </Card>
      <Card title="Meaning before color">
        <Body>Status text always carries the meaning.</Body>
        <Body supporting>
          Approved semantic colors support explicit labels. These are design
          specimens, without financial state.
        </Body>
        <StatusChip label="Verified specimen" status="VERIFIED" />
        <StatusChip label="Pending specimen" status="PENDING" />
        <StatusChip label="Disputed specimen" status="DISPUTED" />
        <StatusChip label="Overdue specimen" status="OVERDUE" />
        <StatusChip label="Closed specimen" status="CLOSED" />
      </Card>
      <Micro>FEEDBACK SPECIMENS</Micro>
      <LoadingState message="Loading specimen" />
      <EmptyState
        title="A little space to begin"
        message="An empty-state specimen, without product data."
      />
      <ErrorState message="An error-state specimen. No request has failed." />
      <Divider />
      <Body supporting>Built on clarity. Designed for people.</Body>
    </Screen>
  );
}
