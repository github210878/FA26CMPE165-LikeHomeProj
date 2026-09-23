import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "LikeHome",
  description: "Find a place that feels like home.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <div className="flex min-h-screen flex-col bg-background text-foreground">
          <a
            href="#main-content"
            className="sr-only z-50 rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white focus:fixed focus:top-4 focus:left-4 focus:not-sr-only"
          >
            Skip to main content
          </a>

          <SiteHeader />

          <main id="main-content" tabIndex={-1} className="min-w-0 flex-1">
            {children}
          </main>

          <SiteFooter />
        </div>
      </body>
    </html>
  );
}
