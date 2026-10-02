import { useCallback, useEffect, useRef, useState } from "react";
import type { Connection } from "@fides/shared/api/connections";
import { ApiError } from "@fides/shared/api/errors";
import { connectionError, connectionRole, type ConnectionAction } from "@fides/shared/connections/model";
import { useAuth } from "../auth/useAuth";

export function useConnections(id?: string) {
  const { state, session, connections } = useAuth();
  const userId = state.status === "authenticated" ? state.user.id : "";
  const [rows, setRows] = useState<Connection[] | null>(null);
  const [detail, setDetail] = useState<Connection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [uncertain, setUncertain] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(false);
  const read = useCallback(async <T,>(get: () => Promise<T>) => {
    try { return await get(); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      await session.bootstrap();
      if (session.snapshot().status !== "authenticated") throw error;
      return get(); // One safe GET recovery only.
    }
  }, [session]);
  const reconcile = useCallback(async () => {
    const version = ++generation.current;
    const [list, row] = await Promise.all([
      read(connections.listConnections), id ? read(() => connections.getConnection(id)) : Promise.resolve(null),
    ]);
    if (list.some(item => !connectionRole(item, userId)) || (row && !connectionRole(row, userId)))
      throw new ApiError("NOT_FOUND", "Unavailable resource.", 404);
    if (mounted.current && version === generation.current) {
      setRows(list); setDetail(row); setUncertain(false);
    }
  }, [connections, id, read, userId]);
  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try { await reconcile(); }
    catch (error) {
      if (mounted.current) {
        setError(connectionError(error));
        if (error instanceof ApiError && error.status === 404) setDetail(null);
      }
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }, [reconcile]);
  useEffect(() => {
    mounted.current = true; inFlight.current = true;
    let cancelled = false;
    void reconcile().catch(error => {
      if (!cancelled) setError(connectionError(error));
    }).finally(() => {
      if (!cancelled) { inFlight.current = false; setBusy(false); }
    });
    return () => { cancelled = true; mounted.current = false; };
  }, [reconcile]);
  const mutate = async (run: () => Promise<Connection>, creating = false) => {
    if (inFlight.current || uncertain) return null;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const row = await run();
      if (!connectionRole(row, userId)) throw new ApiError("INVALID_RESPONSE", "Unavailable resource.", null);
      if (mounted.current) {
        setDetail(current => current?.id === row.id || id === row.id ? row : current);
        setRows(current => current ? [row, ...current.filter(item => item.id !== row.id)] : [row]);
      }
      try { await reconcile(); } catch { if (mounted.current) { setUncertain(true); setError("Request completed. Refresh to confirm the current list."); } }
      return row;
    } catch (failure) {
      if (mounted.current) { setError(connectionError(failure, creating)); setUncertain(true); }
      if (failure instanceof ApiError && failure.status === 401) await session.bootstrap();
      if (session.snapshot().status === "authenticated") {
        try { await reconcile(); }
        catch (failure) { if (mounted.current && failure instanceof ApiError && failure.status === 404) setDetail(null); }
      }
      return null;
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  };
  const action = (action: ConnectionAction, row: Connection) => mutate(() =>
    ({ accept: connections.acceptConnection, reject: connections.rejectConnection,
      block: connections.blockConnection, remove: connections.removeConnection })[action](row.id));
  return { rows, detail, error, busy, uncertain, refresh, action,
    create: (phone: string) => mutate(() => connections.createConnection(phone), true), userId };
}
