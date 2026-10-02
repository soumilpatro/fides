"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@fides/shared/api/errors";
import type { Commitment, CommitmentRequest, Terms, Installment } from "@fides/shared/api/commitments";
import type { Connection } from "@fides/shared/api/connections";
import { commitmentError, commitmentRole, currentTerms, type ProposalAction } from "@fides/shared/commitments/model";
import { useAuth } from "../auth/useAuth";
interface Snapshot { rows: Commitment[]; detail: Commitment | null; terms: Terms | null; installments: Installment[] | null; eligible: Connection[] }
export function useCommitments(id?: string, creation = false) {
  const { state, session, commitments, connections, intents } = useAuth();
  const userId = state.status === "authenticated" ? state.user.id : "";
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false), flight = useRef(false), generation = useRef(0);
  const scope = useCallback((action: "create" | ProposalAction) => userId + ":" + (id ?? "new") + ":" + action, [id, userId]);
  const read = useCallback(async <T,>(get: () => Promise<T>) => {
    try { return await get(); }
    catch (failure) {
      if (!(failure instanceof ApiError) || failure.status !== 401) throw failure;
      await session.bootstrap();
      if (session.snapshot().status !== "authenticated") throw failure;
      return get();
    }
  }, [session]);
  const reconcile = useCallback(async () => {
    const version = ++generation.current;
    const [rows, detail, terms, allConnections] = await Promise.all([
      read(commitments.listCommitments), id ? read(() => commitments.getCommitment(id)) : null,
      id ? read(() => commitments.getCommitmentTerms(id)) : null, creation ? read(connections.listConnections) : [],
    ]);
    if (rows.some(row => !commitmentRole(row, userId)) || (detail && !commitmentRole(detail, userId)))
      throw new ApiError("NOT_FOUND", "Unavailable resource.", 404);
    let installments: Installment[] | null = null;
    if (terms && detail) {
      if (terms.commitment_id !== detail.id || terms.currency !== detail.currency) throw new ApiError("INVALID_RESPONSE", "Unavailable resource.", null);
      const current = currentTerms(terms);
      if (current.schedule_mode === "installments") {
        installments = await read(() => commitments.getCommitmentInstallments(detail.id));
        if (installments.length !== current.installment_dates?.length || installments.some((row,index) => row.terms_version_id !== current.id || row.currency !== detail.currency || row.sequence_no !== index + 1 || row.due_date !== current.installment_dates?.[index]))
          throw new ApiError("INVALID_RESPONSE", "Terms changed. Refresh the record.", null);
      }
    }
    if (mounted.current && generation.current === version) {
      setData({ rows, detail, terms, installments, eligible: allConnections.filter(row => row.status === "ACCEPTED") });
      for (const action of ["create","confirm","reject","cancel"] as const) {
        if (action !== "create" && detail && detail.status !== "PENDING_CONFIRMATION") intents.succeeded(scope(action));
        else intents.reconciled(scope(action));
      }
      setRevision(value => value + 1);
    }
  }, [commitments, connections, creation, id, intents, read, scope, userId]);
  const refresh = useCallback(async () => {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(null);
    try { await reconcile(); }
    catch (failure) {
      if (mounted.current) { setError(commitmentError(failure));
        if (failure instanceof ApiError && failure.status === 404) setData(null); }
    } finally { flight.current = false; if (mounted.current) setBusy(false); }
  }, [reconcile]);
  useEffect(() => {
    mounted.current = true; flight.current = true; let cancelled = false;
    void reconcile().catch(failure => { if (!cancelled) setError(commitmentError(failure)); })
      .finally(() => { if (!cancelled) { flight.current = false; setBusy(false); } });
    return () => { cancelled = true; mounted.current = false; };
  }, [reconcile]);
  const actionBlocked = (action: ProposalAction) => (["confirm","reject","cancel"] as const).some(other => other !== action && !!intents.get(scope(other)));
  const mutate = async (action: "create" | ProposalAction, body?: CommitmentRequest) => {
    if (flight.current || (action !== "create" && actionBlocked(action))) return null;
    const operation = scope(action);
    const payload = action === "create" ? body : {};
    let intent;
    try { intent = intents.begin(operation, payload); }
    catch { setError("Refresh and resolve the pending request before changing or retrying it."); return null; }
    flight.current = true; setBusy(true); setError(null);
    try {
      const row = action === "create" ? await commitments.createCommitment(body!, intent.key) :
        await ({ confirm: commitments.confirmCommitment, reject: commitments.rejectCommitment, cancel: commitments.cancelCommitment })[action](id!, intent.key);
      if (!commitmentRole(row, userId)) throw new ApiError("INVALID_RESPONSE", "Unavailable resource.", null);
      intents.succeeded(operation);
      if (mounted.current && id) setData(previous => previous ? { ...previous, detail: row, terms: null, installments: null } : null);
      try { await reconcile(); } catch { if (mounted.current) setError("Request completed. Refresh to load the current record and terms."); }
      return mounted.current ? row : null;
    } catch (failure) {
      intents.failed(operation, failure);
      if (mounted.current) setError(commitmentError(failure, action === "create"));
      if (failure instanceof ApiError && failure.status === 401) await session.bootstrap();
      if (session.snapshot().status === "authenticated") {
        try { await reconcile(); } catch (failure) {
          if (mounted.current && failure instanceof ApiError && failure.status === 404) setData(null);
        }
      }
      return null;
    } finally { flight.current = false; if (mounted.current) { setBusy(false); setRevision(value => value + 1); } }
  };
  // Revision updates expose pure intent state after transport/reconciliation.
  void revision;
  return { data, error, busy, userId, refresh, pending: (action: "create" | ProposalAction) => intents.get(scope(action)),
    actionBlocked, create: (body: CommitmentRequest) => mutate("create", body), action: (action: ProposalAction) => mutate(action) };
}
