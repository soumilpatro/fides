"use client";
import { useState } from "react";
import {
  Amount,
  Button,
  Card,
  Divider,
  EmptyState,
  ErrorState,
  LoadingState,
  PersonRow,
  StatusChip,
  TextField,
} from "../components/ui";
const sections = ["Typography", "Identity", "Controls", "Feedback"];
export default function Foundation() {
  const [name, setName] = useState("");
  const [message, setMessage] = useState(
    "Actions below affect this preview only.",
  );
  return (
    <>
      <header className="page-header">
        <span className="micro">FIDES / DESIGN FOUNDATION</span>
        <span className="edition">01 — Light</span>
      </header>
      <div className="intro">
        <div className="eyebrow">CLARITY STARTS HERE</div>
        <h1>
          A little structure.
          <br />A lot of understanding.
        </h1>
        <p className="lede">
          The building blocks of Fides. Familiar, considered, and clear — on
          every screen.
        </p>
      </div>
      <div className="preview-note">
        <StatusChip label="Foundation preview" />
        <span>Component examples only. No account or financial activity.</span>
      </div>
      <nav className="section-nav" aria-label="Preview sections">
        {sections.map((section, i) => (
          <a key={section} href={`#${section.toLowerCase()}`}>
            <span className="micro">0{i + 1}</span> {section}
          </a>
        ))}
      </nav>
      <div className="specimen-grid">
        <div id="typography" className="specimen-wide">
          <Card title="Numbers, with room to breathe">
            <p className="supporting">TYPE / AMOUNT HIERARCHY</p>
            <div className="amount-example">
              <Amount minor={123456} currency="INR" />
              <p className="supporting">
                Formatting specimen · illustrative amount, not a balance
              </p>
            </div>
            <Divider />
            <div className="amount-pair">
              <div>
                <span className="micro">CARD AMOUNT</span>
                <Amount size="card" minor={123456} currency="INR" />
              </div>
              <div>
                <span className="micro">ROW AMOUNT</span>
                <Amount size="row" minor={123456} currency="INR" />
              </div>
            </div>
          </Card>
        </div>
        <div id="identity">
          <Card title="People before numbers">
            <p className="supporting">IDENTITY / PERSON ROW</p>
            <PersonRow name="Sample Person" role="Identity specimen" />
            <Divider />
            <h3>Explicit. Never implied.</h3>
            <p>
              Names and roles travel together. A connection is never a
              substitute for permission.
            </p>
          </Card>
        </div>
        <div id="controls">
          <Card title="A clear next step">
            <p className="supporting">CONTROLS / BUTTONS & INPUT</p>
            <TextField
              label="Preview text"
              placeholder="Try a little clarity"
              value={name}
              onChange={(event) => setName(event.target.value)}
              hint="Local preview only. Nothing is submitted or saved."
            />
            <div className="button-row">
              <Button
                onClick={() =>
                  setMessage("Primary button activated. No request was sent.")
                }
              >
                Primary action
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  setMessage("Secondary button activated. No request was sent.")
                }
              >
                Secondary
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  setName("");
                  setMessage("Preview reset.");
                }}
              >
                Reset preview
              </Button>
              <Button disabled>Disabled</Button>
            </div>
            <p className="supporting" role="status">
              {message}
            </p>
          </Card>
        </div>
        <Card title="A calm visual language">
          <p className="supporting">PALETTE / APPROVED COLORS</p>
          <div className="swatches">
            {["Signal", "Human", "Canvas", "Ink", "Border"].map((label) => (
              <div key={label}>
                <span className={`swatch swatch--${label.toLowerCase()}`} />
                <small>{label}</small>
              </div>
            ))}
          </div>
          <Divider />
          <p>Text carries the meaning. Color supports it.</p>
          <p className="supporting">
            Financial status colors await approval; no status palette is implied
            here.
          </p>
        </Card>
      </div>
      <section id="feedback" className="feedback">
        <div className="section-heading">
          <h2>Every state deserves clarity.</h2>
          <span className="micro">FEEDBACK SPECIMENS</span>
        </div>
        <div className="feedback-grid">
          <LoadingState message="Loading specimen" />
          <EmptyState
            title="A little space to begin"
            message="An empty-state specimen, without product data."
          />
          <ErrorState message="An error-state specimen. No request has failed." />
        </div>
      </section>
      <footer className="page-footer">
        <span className="wordmark">FIDES</span>
        <span>Built on clarity. Designed for people.</span>
        <small>Foundation / F0</small>
      </footer>
    </>
  );
}
