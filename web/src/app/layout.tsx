import type { Metadata, Viewport } from "next";
import { Figtree } from "next/font/google";
import { APP_NAME, APP_TAGLINE } from "@/lib/brand";
import { ServiceWorker } from "@/components/ServiceWorker";
import { SoundProvider } from "@/components/SoundProvider";
import { StepFeed } from "@/components/StepFeed";
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
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3210"),
  openGraph: { title: APP_NAME, description: APP_TAGLINE, siteName: APP_NAME, images: [{ url: "/brand/og.png", width: 1200, height: 630, alt: APP_NAME }] },
  twitter: { card: "summary_large_image", title: APP_NAME, description: APP_TAGLINE, images: ["/brand/og.png"] },
  icons: { icon: [{ url: "/icons/favicon-48.png", sizes: "48x48" }, { url: "/icons/icon-192.png", sizes: "192x192" }], apple: "/icons/apple-touch-icon.png" },
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
      <body className="min-h-dvh">
        {children}
        <StepFeed />
        <ServiceWorker />
        <SoundProvider />
      </body>
    </html>
  );
}
