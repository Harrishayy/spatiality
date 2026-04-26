import type { Metadata, Viewport } from "next";
import { Inter, Fraunces } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";
import "./styles/landing.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Spatiality — Glasses → 3D Twin",
  description:
    "Capture with Ray-Ban glasses. Reconstruct in seconds. Ask the room where you are.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#1a0e14",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable}`}>
      <body className="bg-ink-950 text-ink-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
