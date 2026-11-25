import type { Metadata } from "next";
import { Caveat, Patrick_Hand } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const hand = Patrick_Hand({ subsets: ["latin"], weight: "400", variable: "--font-hand", display: "swap" });
const marker = Caveat({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-marker", display: "swap" });

export const metadata: Metadata = {
  title: "Degree Planner",
  description: "Plan your UVM schedule and path to graduation.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${hand.variable} ${marker.variable}`}>
      <body className="font-sans">
        {/* the wobble that makes .sketch outlines look hand-drawn */}
        <svg width="0" height="0" className="absolute" aria-hidden>
          <filter id="wobble">
            <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="7" />
            <feDisplacementMap in="SourceGraphic" scale="3.5" />
          </filter>
        </svg>
        {children}
      </body>
    </html>
  );
}
