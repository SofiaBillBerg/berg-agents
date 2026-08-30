"use client";

import dynamic from "next/dynamic";

const App = dynamic(() => import("../App.tsx"), { ssr: false });

export function ClientOnly() {
  return <App />;
}
