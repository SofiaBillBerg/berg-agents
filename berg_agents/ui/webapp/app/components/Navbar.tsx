/*
 * Navbar component - top navigation bar with links to Chat, Agents, and Stats.
 * Simple div-based navbar (HeroUI v3 doesn't ship a dedicated Navbar).
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

/** Navigation items - links to the three main pages. */
const NAV_ITEMS = [
  { href: "/", label: "Chat", icon: "💬" },
  { href: "/agents", label: "Agents", icon: "🤖" },
  { href: "/stats", label: "Stats", icon: "📊" }];

/**
 * Inner nav links - isolated so `usePathname` always renders inside a
 * Suspense boundary (required during prerender).
 */
function NavLinks() {
  const pathname = usePathname();

  return (
    <div className="flex items-center gap-2">
      {NAV_ITEMS.map(({ href, label, icon }) => {
        const isActive = pathname === href;
        return (
          <Link
            key={href}
            className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              isActive
                ? "bg-accent/10 text-accent"
                : "text-foreground/70 hover:text-foreground hover:bg-surface-soft"
            }`}
            href={href}
          >
            <span>{icon}</span>
            {label}
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Navbar component - renders a simple top navigation bar.
 * Highlights the active page and provides links between Chat, Agents, and Stats.
 */
export function Navbar() {
  return (
    <nav className="border-b border-border bg-surface-secondary px-4 py-2 flex items-center justify-between">
      <span className="font-bold text-lg text-foreground">Berg Agents</span>
      <Suspense fallback={<div className="flex items-center gap-2" />}>
        <NavLinks />
      </Suspense>
    </nav>
  );
}

export default Navbar;
