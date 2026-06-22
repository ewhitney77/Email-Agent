import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Match Dashboard",
  description: "Open roles at target companies, stack-ranked by semantic match score.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
