"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import { getShortlist, removeShortlistHotel, saveShortlistHotel } from "@/lib/shortlist";

type LoadStatus = "idle" | "loading" | "ready" | "error";
type Operation = { pending: boolean; message: string; error: boolean };
type ShortlistContextValue = {
  status: LoadStatus;
  saved: Set<string>;
  operations: Record<string, Operation>;
  load: (retry?: boolean) => Promise<void>;
  toggle: (token: string) => Promise<void>;
};

const ShortlistContext = createContext<ShortlistContextValue | null>(null);

type Snapshot = { owner: string; status: LoadStatus; saved: Set<string>; operations: Record<string, Operation> };
const emptySnapshot = (owner: string): Snapshot => ({ owner, status: "idle", saved: new Set(), operations: {} });
const newSession = (owner: string) => ({ owner, active: true, read: null as Promise<void> | null, started: false, pending: new Set<string>() });
type Session = ReturnType<typeof newSession>;

export function ShortlistProvider({ children }: { children: ReactNode }) {
  const { status: authStatus, user, invalidateSession } = useAuth();
  const owner = `${authStatus}:${user?.user_id ?? "guest"}`;
  const [snapshot, setSnapshot] = useState(() => emptySnapshot(owner));
  const sessionRef = useRef(newSession(owner));

  if (snapshot.owner !== owner) setSnapshot(emptySnapshot(owner));
  const { status, saved, operations } = snapshot;

  const getSession = useCallback(() => {
    if (sessionRef.current.owner !== owner) sessionRef.current = newSession(owner);
    return sessionRef.current;
  }, [owner]);

  useEffect(() => {
    const session = getSession();
    session.active = true;
    return () => { session.active = false; };
  }, [getSession]);

  const update = useCallback((session: Session, change: (current: Snapshot) => Snapshot) => {
    if (!session.active || sessionRef.current !== session) return;
    setSnapshot((current) => current.owner === owner ? change(current) : current);
  }, [owner]);

  const load = useCallback(async (retry = false) => {
    if (authStatus !== "authenticated") return;
    const session = getSession();
    if (session.read) return session.read;
    if (session.started && !retry) return;
    session.started = true;
    update(session, (current) => ({ ...current, status: "loading" }));
    session.read = (async () => {
      try {
        const tokens = await getShortlist();
        update(session, (current) => ({ ...current, saved: new Set(tokens), status: "ready" }));
      } catch (error) {
        if (!session.active || sessionRef.current !== session) return;
        if (error instanceof ApiError && error.status === 401) invalidateSession();
        update(session, (current) => ({ ...current, status: "error" }));
      } finally {
        session.read = null;
      }
    })();
    return session.read;
  }, [authStatus, invalidateSession, getSession, update]);

  async function toggle(token: string) {
    const session = getSession();
    if (authStatus !== "authenticated" || status !== "ready" || session.pending.has(token)) return;
    session.pending.add(token);
    const removing = saved.has(token);
    update(session, (current) => ({ ...current, operations: { ...current.operations, [token]: { pending: true, message: "", error: false } } }));
    try {
      if (removing) await removeShortlistHotel(token);
      else await saveShortlistHotel(token);
      update(session, (current) => {
        const next = new Set(current.saved);
        if (removing) next.delete(token);
        else next.add(token);
        return { ...current, saved: next, operations: { ...current.operations, [token]: { pending: false, message: removing ? "Removed from your shortlist." : "Saved to your shortlist.", error: false } } };
      });
    } catch (error) {
      if (!session.active || sessionRef.current !== session) return;
      if (error instanceof ApiError && error.status === 401) invalidateSession();
      update(session, (current) => ({ ...current, operations: { ...current.operations, [token]: { pending: false, message: removing ? "Could not remove this stay. Please try again." : "Could not save this stay. Please try again.", error: true } } }));
    } finally {
      session.pending.delete(token);
    }
  }

  return <ShortlistContext.Provider value={{ status, saved, operations, load, toggle }}>{children}</ShortlistContext.Provider>;
}

export function useShortlist() {
  const context = useContext(ShortlistContext);
  if (!context) throw new Error("useShortlist requires ShortlistProvider");
  return context;
}
