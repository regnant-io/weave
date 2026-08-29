import { NextResponse, type NextRequest } from "next/server";

/**
 * Route gating at the edge.
 *
 * WHY THIS EXISTS: the dashboard "peek" on first run.
 *
 * The auth and onboarding checks used to live inside the page components as
 * `if (!authed) redirect(...)`. That is correct but it is too late. A signed-up
 * user landing on `/app/projects` for the first time went:
 *
 *   1. the client navigates, and Next renders the shared layout — sidebar,
 *      rail, floating controls — because the layout is above the page in the
 *      tree and does not know the page is about to bail;
 *   2. the page's server component runs and calls `redirect("/onboarding")`;
 *   3. the client fetches `/onboarding` and finally swaps.
 *
 * Step 1 paints. The user sees the whole application for a beat before being
 * dropped into a first-run flow that is supposed to introduce it — which is
 * both a flash of the wrong screen and a spoiler for the thing onboarding is
 * about to explain.
 *
 * Middleware runs before any of that. A request that is going to be redirected
 * is redirected while it is still a request, so nothing renders and nothing
 * paints. The in-page guards are kept as defence in depth (middleware can be
 * bypassed by a direct RSC fetch in some deployments), but they are no longer
 * the thing the user experiences.
 *
 * COOKIES ONLY. Middleware runs on the edge runtime with no database, so it
 * decides from `weave_token` (presence, not validity) and `weave_onboarded`.
 * Validity is still enforced by the API on every call — a forged or expired
 * token gets past this and is rejected one layer down, which is the correct
 * split: this is a routing concern, not an authorisation one.
 */

const TOKEN_COOKIE = "weave_token";
const ONBOARDED_COOKIE = "weave_onboarded";

/** Signed-in area. Everything here needs a token. */
const PRIVATE_PREFIXES = ["/app", "/admin", "/onboarding"];

/**
 * Exceptions inside the private area.
 *
 * The library is deliberately browsable without an account — it is the "try it
 * without signing up" entry point on the landing page, and it happens to live
 * under `/app`.
 */
const PUBLIC_INSIDE_APP = ["/app/library"];

/** Pages that only make sense when signed OUT. */
const AUTH_PAGES = ["/auth/login", "/auth/register", "/auth/verify-otp"];

function startsWithAny(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  const authed = Boolean(token);
  const onboarded = req.cookies.get(ONBOARDED_COOKIE)?.value === "1";

  const isPublicInApp = startsWithAny(pathname, PUBLIC_INSIDE_APP);
  const isPrivate = startsWithAny(pathname, PRIVATE_PREFIXES) && !isPublicInApp;

  // 1. Signed out, asking for something private → login, remembering where.
  if (isPrivate && !authed) {
    const url = req.nextUrl.clone();
    url.pathname = "/auth/login";
    url.search = "";
    // So the user lands where they were going instead of on a generic home.
    if (pathname !== "/app/projects") url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }

  // 2. Signed in but never set up → onboarding, before any app chrome renders.
  //    `/onboarding` itself is excluded or this would loop.
  if (isPrivate && authed && !onboarded && !pathname.startsWith("/onboarding")) {
    const url = req.nextUrl.clone();
    url.pathname = "/onboarding";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // 3. Signed in and set up, but sitting on the landing or an auth page →
  //    straight into the app. Re-showing "choose student or researcher" to
  //    someone who already chose is a small thing that reads as broken.
  if (authed && onboarded && (pathname === "/" || AUTH_PAGES.includes(pathname))) {
    const url = req.nextUrl.clone();
    url.pathname = "/app/projects";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  /*
    Everything except: Next's own assets, the route handlers under /api (they
    proxy to the backend and do their own auth — bouncing them to an HTML login
    page would turn a 401 into an unparseable redirect), the service worker, and
    static files with an extension.
  */
  matcher: ["/((?!api/|_next/|sw\\.js|manifest\\.webmanifest|.*\\.[\\w]+$).*)"],
};
