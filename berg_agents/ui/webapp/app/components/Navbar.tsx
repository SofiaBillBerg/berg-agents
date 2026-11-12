/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * Navbar component - top navigation bar with links to Chat, Agents, and Stats.
 * Simple div-based navbar (HeroUI v3 doesn't ship a dedicated Navbar).
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

/** Navigation items - links to the main pages. */
const NAV_ITEMS = [
  { href: "/", label: "Chat", icon: "💬" },
  { href: "/agents", label: "Agents", icon: "🤖" },
  { href: "/context", label: "Context", icon: "📚" },
  { href: "/history", label: "History", icon: "🕘" },
  // Plugin dev harness: standalone route for working on plugin
  // surfaces and tools without a live agent run.
  { href: "/dev/plugins", label: "Dev", icon: "🧩" }];

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
                ? "bg-white/20 text-white"
                : "text-white/75 hover:text-white hover:bg-white/10"
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
    // Brand banner: Sofia's purple → blue → teal gradient, same as the
    // docs header. White text both modes; the gradient pops on its own
    // so no surface tokens are used here.
    <nav
      className="px-4 py-1.5 flex items-center justify-between"
      style={{ background: "var(--berg-gradient-brand)" }}
    >
      <span className="font-bold text-base text-white">Berg Agents</span>
      <Suspense fallback={<div className="flex items-center gap-2" />}>
        <NavLinks />
      </Suspense>
    </nav>
  );
}

export default Navbar;
