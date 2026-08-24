import type { NextConfig } from "next";

/**
 * Extra hostnames allowed to request the dev server.
 *
 * Next blocks cross-origin requests to dev-only assets, so reaching `next dev`
 * from a phone or tablet on the LAN needs that device's host listed. The value
 * differs per developer and per network, so it comes from the environment
 * rather than the repository — the same shape as the backend's
 * CORS_ALLOW_ORIGINS:
 *
 *   ALLOWED_DEV_ORIGINS=192.168.1.20 bun dev --hostname 0.0.0.0
 *
 * Deliberately not NEXT_PUBLIC_: this configures the dev server and must never
 * reach a browser bundle.
 */
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  // Omitted entirely when unset, so the default localhost-only behaviour stands.
  ...(allowedDevOrigins.length > 0 ? { allowedDevOrigins } : {}),
};

export default nextConfig;
