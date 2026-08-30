import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: "Berg Agents Web UI",
  description: "A web interface for the Berg Agents application.",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div id="root">{children}</div>
      </body>
    </html>
  );
}
