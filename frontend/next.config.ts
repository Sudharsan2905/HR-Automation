import type { NextConfig } from "next";

// Where the FastAPI backend runs. The browser calls "/api/..." on the frontend's own origin and Next
// forwards it here, so there is no cross-origin (CORS) request - it works on localhost and behind ngrok.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8001";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
