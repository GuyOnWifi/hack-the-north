import type { NextConfig } from "next";

// Lane B's API (bricolage/server.py). The browser only ever talks to this app,
// which forwards /bricolage/* there, so phones on the LAN work without CORS.
const BRICOLAGE_URL = process.env.BRICOLAGE_URL ?? "http://127.0.0.1:8017";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [{ source: "/bricolage/:path*", destination: `${BRICOLAGE_URL}/api/:path*` }];
  },
};

export default nextConfig;
