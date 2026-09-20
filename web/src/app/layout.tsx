import type { Metadata, Viewport } from "next";
import { Figtree } from "next/font/google";
import { APP_NAME, APP_TAGLINE } from "@/lib/brand";
import { ServiceWorker } from "@/components/ServiceWorker";
import "./globals.css";

const figtree = Figtree({
  variable: "--font-figtree",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800", "900"],
});

export const metadata: Metadata = {
  title: APP_NAME,
  description: APP_TAGLINE,
  applicationName: APP_NAME,
  appleWebApp: { capable: true, title: APP_NAME, statusBarStyle: "black-translucent" },
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: "#f5b200",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${figtree.variable} h-full antialiased`}>
      {/* Desktop: the phone-width app sits centred on a dark studio backdrop and
          is lifted with a soft shadow (a phone on a desk) instead of floating in
          a gray void. On mobile the column is full-bleed and none of this shows. */}
      <body className="min-h-dvh" style={{ background: "radial-gradient(130% 100% at 50% 0%, #232838 0%, #0d0f14 72%)" }}>
        <div className="relative mx-auto min-h-dvh w-full max-w-[520px] bg-page shadow-[0_0_140px_rgba(0,0,0,0.6)]">
          {children}
        </div>
        <ServiceWorker />
      </body>
    </html>
  );
}
