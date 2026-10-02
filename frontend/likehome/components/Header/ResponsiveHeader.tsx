"use client";

import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { authenticatedNavLinks, publicNavLinks, restoringNavLinks } from "@/constants/constant";
import SiteHeader from "./SiteHeader";
import MobileHeader from "./MobileHeader";

export default function ResponsiveHeader() {
  const [showHead, setShowHead] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [notice, setNotice] = useState("");
  const { status, signOut } = useAuth();
  const links = status === "authenticated" ? authenticatedNavLinks :
    status === "unauthenticated" ? publicNavLinks : restoringNavLinks;

  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    const revoked = await signOut();
    setNotice(revoked ? "" : "Signed out on this device. The server could not confirm logout.");
    setShowHead(false);
    setSigningOut(false);
  }

  return (
    <div>
      <SiteHeader links={links} status={status} signingOut={signingOut}
        openHead={() => setShowHead(true)} signOut={handleSignOut} />
      <MobileHeader links={links} status={status} signingOut={signingOut}
        showHead={showHead} closeHead={() => setShowHead(false)} signOut={handleSignOut} />
      {notice && <p role="status" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">{notice}</p>}
    </div>
  );
}
