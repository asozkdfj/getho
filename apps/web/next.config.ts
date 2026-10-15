import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // monorepo: trace files from the repository root so the standalone build
  // includes the workspace package (@edge/contracts)
  outputFileTracingRoot: path.join(__dirname, "../.."),
  transpilePackages: ["@edge/contracts"],
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
