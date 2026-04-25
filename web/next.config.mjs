/** @type {import('next').NextConfig} */
const nextConfig = {
  // Off in dev: SplatViewer wraps an imperative WebGL viewer
  // (@mkkellogg/gaussian-splats-3d) whose dispose() does not fully tear down
  // its DOM children. Strict mode's double-invoked effect leaves orphan canvases
  // in the container, which then trips React's removeChild on the next render.
  reactStrictMode: false,
  async rewrites() {
    const agent = process.env.NEXT_PUBLIC_AGENT_URL;
    if (!agent) return [];
    return [
      { source: "/api/:path*", destination: `${agent}/api/:path*` },
      { source: "/artifacts/:path*", destination: `${agent}/artifacts/:path*` },
    ];
  },
};

export default nextConfig;
