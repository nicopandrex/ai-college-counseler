import type { Metadata } from "next";
import { Jost } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const jost = Jost({ subsets: ["latin"], variable: "--font-jost", display: "swap" });

export const metadata: Metadata = {
  title: "Degree Planner",
  description: "Plan your UVM schedule and path to graduation.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={jost.variable}>
      <body className="font-sans">{children}</body>
    </html>
  );
}
