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
 * Navbar component - top navigation bar built with shadcn NavigationMenu.
 */
"use client";

import { usePathname } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";

import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList} from "@/components/ui/navigation-menu";
import { cn } from "@/lib/utils";

/** Navigation items - links to the main pages. */
const NAV_ITEMS = [
  { href: "/orchestrator", label: "Orchestrator", icon: "🧠" },
  { href: "/", label: "Chat", icon: "💬" },
  { href: "/agents", label: "Agents", icon: "🤖" },
  { href: "/specialists", label: "Specialists", icon: "🧬" },
  { href: "/context", label: "Context", icon: "📚" },
  { href: "/history", label: "History", icon: "🕘" },
  { href: "/dev/plugins", label: "Dev", icon: "🧩" }];

function NavLinks() {
  const pathname = usePathname();

  return (
    <NavigationMenuList className="flex flex-row items-center gap-1.5">
      {NAV_ITEMS.map(({ href, label, icon }) => {
        const isActive = pathname === href;
        return (
          <NavigationMenuItem key={href}>
            <NavigationMenuLink
              className={cn(
                "inline-flex flex-row items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-white/20 text-white hover:bg-white/25 focus:bg-white/25"
                  : "text-white/75 hover:bg-white/10 hover:text-white focus:bg-white/10 focus:text-white",
              )}
              href={href}
              isCurrent={isActive}
            >
              <span>{icon}</span>
              <span>{label}</span>
            </NavigationMenuLink>
          </NavigationMenuItem>
        );
      })}
    </NavigationMenuList>
  );
}

export function Navbar() {
  return (
    <header
      className="flex items-center justify-between px-4 py-1.5"
      style={{ background: "var(--berg-gradient-brand)" }}
    >
      <Link
        className="text-base font-bold text-white transition-opacity hover:opacity-90"
        href="/"
      >
        Berg Agents
      </Link>

      <NavigationMenu aria-label="Main navigation" viewport={false}>
        <Suspense fallback={<div className="h-8" />}>
          <NavLinks />
        </Suspense>
      </NavigationMenu>
    </header>
  );
}

export default Navbar;
