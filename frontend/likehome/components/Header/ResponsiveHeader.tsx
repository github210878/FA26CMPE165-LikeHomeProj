"use client";
import Link from "next/link";
import React, { useState } from "react";
import SiteHeader from "./SiteHeader";
import MobileHeader from "./MobileHeader";

const ResponsiveHeader = () => {
  const [showHead, setShowHead] = useState(false);

  const openHeadHandler = () => setShowHead(true);
  const closeHeadHandler = () => setShowHead(false);

  return (
    <div>
      <SiteHeader openHead={openHeadHandler} />
      <MobileHeader showHead = {showHead} closeHead={closeHeadHandler}/>
    </div>
  );
};

export default ResponsiveHeader;
