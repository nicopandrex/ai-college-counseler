/** @type {import('next').NextConfig} */
const api = process.env.API_URL ?? "http://127.0.0.1:8000"; // the planner_api server

const nextConfig = {
  reactStrictMode: true,
  // reading a new audit takes about a minute (LLM extraction); the default proxy timeout is 30 s
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
