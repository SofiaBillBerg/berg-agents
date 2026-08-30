
// Theme is imported from JS so next.js resolves it as a real CSS asset
// (the @import url(...) trick inside styles.css does not survive bundling).
import "../theme.js";
// Import component styles
import "../styles.css";
import "../globals.css";
import { ClientOnly } from "./client";
// Global error handler to catch uncaught errors
window.addEventListener("error", (event) => {
    console.error("Global error:", event.error);
});

window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled promise rejection:", event.reason);
});

export function generateStaticParams() {
  return [{ slug: [""] }];
}
export default function Page() {
  return <ClientOnly />;
}
