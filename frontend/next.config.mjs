/**
 * Next.js configuration.
 *
 * NB (architecture constraint): there is deliberately NO Vite here. Next.js ships
 * its own bundler (Webpack/Turbopack) and dev server, which is why choosing Next
 * already satisfies the "no Vite" constraint without any workaround.
 *
 * WEAVE_API_BASE is read at RUNTIME by server-side code (src/lib/api.ts and the
 * route handlers). We deliberately do NOT put it in Next's `env` block, because
 * that would inline the build-time value into the bundle and ignore the runtime
 * env — breaking the containerised case where the value must be http://backend:8000.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Compression is handled at the CDN (Brotli) per architecture 4.1; Next also
  // gzips by default in production.
  compress: true,
  async rewrites() {
    // Evaluated at server start (runtime), so it picks up the live env value.
    const backend = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";
    return [{ source: "/api/backend-health", destination: `${backend}/health` }];
  },
};

export default nextConfig;
