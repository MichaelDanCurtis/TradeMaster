/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  reactStrictMode: true,
  ...(process.env.TRADEMASTER_DESKTOP_BUILD === "1" ? { output: "standalone" } : {})
};

export default nextConfig;
