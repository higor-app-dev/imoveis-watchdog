import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  env: {
    TURSO_HERMES_DATA_DB_URL: process.env.TURSO_HERMES_DATA_DB_URL || "",
    TURSO_HERMES_DATA_DB_TOKEN: process.env.TURSO_HERMES_DATA_DB_TOKEN || "",
  },
};

export default nextConfig;
