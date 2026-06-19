/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy API calls to the FastAPI backend to avoid CORS in dev and keep
  // the GROQ_API_KEY strictly server-side.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/:path*` },
    ];
  },
};

export default nextConfig;
