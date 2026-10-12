import type {Metadata} from "next";

import React from "react";
import {Public_Sans} from "next/font/google";

import "./globals.css";

/**
 * Public Sans, self-hosted via next/font. The `variable` option exposes
 * `--font-public-sans`, which is exactly what the HeroUI `--font-sans`
 * token in globals.css (Sofia's builder theme) points at.
 */
const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-public-sans",
  display: "swap"});

export const metadata: Metadata = {
  title: "Berg Agents Web UI",
  description: "A web interface for the Berg Agents application.",
  icons: {
    icon: [
      { url: "/favicon/favicon.ico" },
      { url: "/favicon/favicon-96x96.png", sizes: "96x96", type: "image/png" },
      { url: "/favicon/favicon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/favicon/apple-touch-icon.png", sizes: "180x180" }]},
  manifest: "/favicon/site.webmanifest"};

/**
 * Pre-hydration theme script: reads the stored theme (`berg-theme`, falling
 * back to the legacy `berg-preset` key) or the OS preference and applies the
 * `.dark` class + `data-theme` before first paint, so the correct HeroUI
 * tokens apply with no light-flash. Must stay dependency-free and inline.
 */
const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem("berg-theme")||localStorage.getItem("berg-preset");var d=s?s==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches;var r=document.documentElement;r.classList.toggle("dark",d);r.setAttribute("data-theme",d?"dark":"light");r.setAttribute("data-berg-preset",d?"dark":"light");}catch(e){}})();`;

export default function RootLayout({
  children}: {
  children: React.ReactNode;
}) {
  return (
    <html
      suppressHydrationWarning
      className={publicSans.variable}
      lang="en"
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="flex h-dvh flex-col overflow-hidden">
        <div id="root" className="flex min-h-0 flex-1 flex-col">
          {children}
        </div>
      </body>
    </html>
  );
}
