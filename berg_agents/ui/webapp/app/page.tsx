/**
 * Main landing page for the Berg Agents web application.
 * Imports theme assets and renders the interactive client application.
 */

import "./theme.js";
import {ClientOnly} from "./client.tsx";

/**
 * Root Page component for Next.js App Router.
 *
 * @returns JSX element rendering the client-only application.
 */
export default function Page() {
    return <ClientOnly/>;
}
