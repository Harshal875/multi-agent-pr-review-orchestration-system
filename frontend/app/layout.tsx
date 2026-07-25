import "./globals.css";
import type { Metadata } from "next";
import Nav from "./components/Nav";

export const metadata: Metadata = {
  title: "AI PR-Review Dashboard",
  description: "Reviews, HITL queue, trace viewer, and cost for the AI PR-review agent.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
