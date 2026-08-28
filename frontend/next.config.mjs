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
  compress: true,
  
  compiler: {
    // Remove console.log in production
    removeConsole: process.env.NODE_ENV === 'production',
  },

  /*
    Browser floor is declared in package.json "browserslist" (iOS 14+), which is
    what SWC compiles against. `transpilePackages` cannot help with the failure
    we actually hit: react-markdown's `mdast-util-gfm-autolink-literal` contains
    a regex LOOKBEHIND, which no transpiler can lower — it is a runtime regex
    feature, and it is a parse-time SyntaxError on Safari < 16.4. That dependency
    is gone; markdown is rendered by src/lib/markdown, which is lookbehind-free.
  */
  transpilePackages: ['lucide-react'],

  async rewrites() {
    const backend = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";
    return [{ source: "/api/backend-health", destination: `${backend}/health` }];
  },
};

export default nextConfig;
