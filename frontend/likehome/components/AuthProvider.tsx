"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { createSession, endSession, restoreSession } from "@/lib/auth";
import type { CurrentUserResponse, LoginUserRequest } from "@/lib/api-types";
import { clearAccessToken } from "@/lib/token-storage";

type AuthStatus = "restoring" | "authenticated" | "unauthenticated";
type AuthContextValue = {
  status: AuthStatus;
  user: CurrentUserResponse | null;
  signIn: (credentials: LoginUserRequest) => Promise<void>;
  signOut: () => Promise<boolean>;
  invalidateSession: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("restoring");
  const [user, setUser] = useState<CurrentUserResponse | null>(null);

  useEffect(() => {
    let active = true;
    restoreSession().then((restoredUser) => {
      if (!active) return;
      setUser(restoredUser);
      setStatus(restoredUser ? "authenticated" : "unauthenticated");
    });
    return () => { active = false; };
  }, []);

  async function signIn(credentials: LoginUserRequest): Promise<void> {
    const verifiedUser = await createSession(credentials);
    setUser(verifiedUser);
    setStatus("authenticated");
  }

  async function signOut(): Promise<boolean> {
    const revoked = await endSession();
    setUser(null);
    setStatus("unauthenticated");
    return revoked;
  }

  const invalidateSession = useCallback(() => {
    clearAccessToken();
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  return (
    <AuthContext.Provider value={{ status, user, signIn, signOut, invalidateSession }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth requires AuthProvider");
  return context;
}
