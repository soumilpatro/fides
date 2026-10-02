"use client";
import {
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { formatMoney } from "@fides/shared/domain/money";
import { statusColors, type SemanticStatus } from "@fides/shared/tokens/index";

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "quiet" | "destructive";
}) {
  return (
    <button
      {...props}
      type={type}
      className={`button button--${variant} ${className}`}
    />
  );
}
export function TextField({
  label,
  hint,
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <div className="field">
      <label htmlFor={fieldId}>{label}</label>
      <input
        {...props}
        id={fieldId}
        aria-describedby={hint ? `${fieldId}-hint` : undefined}
      />
      {hint ? <small id={`${fieldId}-hint`}>{hint}</small> : null}
    </div>
  );
}
export function Card({
  children,
  title,
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <section className="card">
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  );
}
/** Presentation only: explicit text carries meaning, never derives a server state. */
export function StatusChip({ label, status }: { label: string; status?: SemanticStatus }) {
  const color = status ? statusColors[status] : null;
  return <span className="chip" style={color ? { color: color.text, background: color.background, borderColor: color.border } : undefined}>{label}</span>;
}
export function Avatar({ name }: { name: string }) {
  const initials = name
    .trim()
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("");
  return (
    <span className="avatar" aria-hidden="true">
      {initials}
    </span>
  );
}
export function PersonRow({ name, role }: { name: string; role: string }) {
  return (
    <div className="person">
      <Avatar name={name} />
      <div>
        <strong>{name}</strong>
        <div className="supporting">{role}</div>
      </div>
    </div>
  );
}
export function Amount({
  minor,
  currency,
  size = "hero",
}: {
  minor: number;
  currency: string;
  size?: "hero" | "card" | "row";
}) {
  return (
    <span className={`amount amount--${size}`}>
      {formatMoney(minor, currency)}
    </span>
  );
}
export function Container({ children }: { children: ReactNode }) {
  return <div className="container">{children}</div>;
}
export function Screen({ children }: { children: ReactNode }) {
  return (
    <main id="main-content" tabIndex={-1}>
      <Container>{children}</Container>
    </main>
  );
}
export function Divider() {
  return <hr className="divider" />;
}
export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="state" role="status">
      <span className="state-mark" aria-hidden="true">
        ···
      </span>
      <strong>{message}</strong>
    </div>
  );
}
export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="state">
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}
export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state state--error" role="alert">
      <strong>Unable to continue</strong>
      <p>{message}</p>
    </div>
  );
}
