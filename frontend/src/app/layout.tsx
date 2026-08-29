import type { Metadata, Viewport } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { getLanguage, getTheme, isAuthed } from "@/lib/session";
import AppShell from "@/components/shell/AppShell";
import BootProbe from "@/components/BootProbe";

/*
  Type stack, self-hosted by next/font (no third-party request at runtime, no
  FOUT).

  This was an editorial pairing — Instrument Serif for display, Fraunces for the
  answer column. It has been replaced wholesale with a single grotesque plus a
  true monospace. The serifs gave the product a magazine voice it was not
  actually speaking in: Weave is a working instrument for students and
  researchers, and it should read like precise machinery, not like a feature
  article. One neutral typeface carrying display, reading and UI also means the
  three never disagree about the rhythm of a line.

    display / read / ui — Geist. Engineered, tight, neutral; built for
      interfaces, and calm enough at 16-17px to hold a long Kiswahili paragraph.
    mono — JetBrains Mono. Designed for reading code at small sizes: tall
      x-height, unmistakable 0/O and 1/l/I, and it carries the eyebrows, step
      chips, figures and code blocks that give the UI its instrument feel.

  `adjustFontFallback` is left on (default) so the fallback metrics are matched
  and there is no layout shift when the webfont lands.
*/
const geist = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-ui-src",
  fallback: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono-src",
  style: ["normal", "italic"],
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
});

export const metadata: Metadata = {
  title: "Weave",
  description:
    "Bilingual (Kiswahili/English) study and research workspace for Tanzanian students and researchers.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Weave", statusBarStyle: "black-translucent" },
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0b0a" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [language, authed, theme] = await Promise.all([getLanguage(), isAuthed(), getTheme()]);
  const htmlThemeAttr = theme === "light" || theme === "dark" ? theme : undefined;
  // Display and read are the same face as UI now, so one variable feeds all
  // three roles in globals.css rather than three families feeding four.
  const fontVars = `${geist.variable} ${jetbrains.variable}`;
  const isProduction = process.env.NODE_ENV === "production";

  return (
    <html
      lang={language}
      className={fontVars}
      {...(htmlThemeAttr ? { "data-theme": htmlThemeAttr } : {})}
      /*
        The blocking script below intentionally mutates <html> before React
        hydrates: it stamps `data-theme` from the cookie so there is no flash of
        the wrong theme. That is precisely the server/client divergence React
        warns about, and it is correct here — the alternative is a visible flash
        on every load. Suppression is one level deep and does not affect any
        child.

        NOTE for anyone tempted to add another class here the way `no-js` used
        to be added: `className` is reconciled on every client-side navigation,
        so a class the server renders and a script removes WILL come back. Only
        attributes whose server value already matches the intended client value
        (like `data-theme`, read from the same cookie on both sides) are safe.
      */
      suppressHydrationWarning
    >
      <head>
        {/*
          Runtime shims for the browsers .browserslistrc actually claims to
          support. SWC lowers SYNTAX for old targets but never adds missing
          RUNTIME methods, and React/Next internals call Object.hasOwn and
          Array.prototype.at — both Safari 15.4+. On an iPad below that, the
          first call throws inside React's render and the screen goes blank.
          This must run BEFORE any bundle, hence a blocking head script.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{" +
              "if(!Object.hasOwn){Object.defineProperty(Object,'hasOwn',{value:function(o,k){" +
              "if(o==null)throw new TypeError('Cannot convert undefined or null to object');" +
              "return Object.prototype.hasOwnProperty.call(Object(o),k);},configurable:true,writable:true});}" +
              "if(!Array.prototype.at){Object.defineProperty(Array.prototype,'at',{value:function(n){" +
              "n=Math.trunc(n)||0;if(n<0)n+=this.length;if(n<0||n>=this.length)return undefined;return this[n];" +
              "},configurable:true,writable:true});}" +
              "if(!String.prototype.at){Object.defineProperty(String.prototype,'at',{value:function(n){" +
              "n=Math.trunc(n)||0;if(n<0)n+=this.length;if(n<0||n>=this.length)return undefined;return this[n];" +
              "},configurable:true,writable:true});}" +
              "if(!String.prototype.replaceAll){Object.defineProperty(String.prototype,'replaceAll',{value:function(s,r){" +
              "if(Object.prototype.toString.call(s)==='[object RegExp]')return this.replace(s,r);" +
              "return this.split(s).join(r);},configurable:true,writable:true});}" +
              "if(!window.requestIdleCallback){window.requestIdleCallback=function(cb){" +
              "return setTimeout(function(){var t=Date.now();cb({didTimeout:false,timeRemaining:function(){" +
              "return Math.max(0,50-(Date.now()-t));}});},1);};" +
              "window.cancelIdleCallback=function(id){clearTimeout(id);};}" +
              "}catch(e){}})();",
          }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var m=document.cookie.match(/weave_theme=(light|dark)/);if(m){document.documentElement.setAttribute('data-theme',m[1]);}else{document.documentElement.removeAttribute('data-theme');}}catch(e){}" +
              // Bundle watchdog. If the app has not hydrated within the window
              // below, the JS genuinely did not arrive (a dropped chunk on a bad
              // connection is a normal event for this audience) and we say so.
              // `BootProbe` clears this the moment a client component mounts.
              "window.__weaveBootTimer=setTimeout(function(){" +
              "try{var b=document.getElementById('weave-boot-warning');if(b)b.hidden=false;}catch(e){}" +
              "},9000);" +
              // Register the worker, and when a NEW one is waiting, activate it
              // immediately instead of leaving a stale shell serving old chunks
              // until every tab closes. `controllerchange` reloads once so the
              // page and the worker agree on which build is live.
              //
              // PRODUCTION ONLY. The worker serves /_next/static/ cache-first,
              // which is correct in production because those filenames are
              // content-hashed. In development they are NOT — the same path is
              // re-served with new contents on every edit — so the worker
              // pinned the first build of the session and every subsequent
              // change was invisible until someone thought to clear site data.
              // A dev server that silently serves yesterday's bundle is a
              // spectacular way to lose an afternoon.
              (isProduction
                ? "if('serviceWorker' in navigator){" +
              "window.addEventListener('load',function(){" +
              "navigator.serviceWorker.register('/sw.js').then(function(reg){" +
              "if(reg.waiting){reg.waiting.postMessage('weave-skip-waiting');}" +
              "reg.addEventListener('updatefound',function(){" +
              "var w=reg.installing;if(!w)return;" +
              "w.addEventListener('statechange',function(){" +
              "if(w.state==='installed'&&navigator.serviceWorker.controller){w.postMessage('weave-skip-waiting');}" +
              "});});" +
              "reg.update();" +
              "}).catch(function(){});" +
              "var reloaded=false;" +
              "navigator.serviceWorker.addEventListener('controllerchange',function(){" +
              "if(reloaded)return;reloaded=true;window.location.reload();" +
              "});});" +
              "}"
                : // Development: actively tear down a worker left behind by a
                  // previous production build on the same origin, or the stale
                  // cache outlives the decision above.
                  "if('serviceWorker' in navigator&&navigator.serviceWorker.getRegistrations){" +
                  "navigator.serviceWorker.getRegistrations().then(function(rs){" +
                  "rs.forEach(function(r){r.unregister();});}).catch(function(){});" +
                  "if(window.caches&&caches.keys){caches.keys().then(function(ks){" +
                  "ks.forEach(function(k){if(k.indexOf('weave-')===0)caches.delete(k);});" +
                  "}).catch(function(){});}" +
                  "}"),
          }}
        />
      </head>
      <body className="bg-bg text-fg">
        {/*
          TWO DIFFERENT FAILURES, TWO DIFFERENT MECHANISMS.

          This used to be one div, hidden by a `.no-js` class that the server
          rendered onto <html> and a head script removed. That is wrong in a way
          that only shows up in use: `className` is part of the React tree, so
          every client-side navigation re-commits the SERVER's value and puts
          `no-js` straight back — on an app whose JavaScript is plainly working,
          because it is the JavaScript doing the navigating. The warning
          therefore appeared for the first time the moment the user proved it
          false, which is the worst possible moment.

          `<noscript>` is the right primitive for "scripting is off": the
          browser owns it, React never touches it, and it cannot be resurrected
          by a re-render.

          A dropped bundle is a different condition and needs a different test —
          scripting is enabled, the chunk just never arrived, which on a
          throttled connection is an ordinary event rather than an edge case. A
          timer set in <head> reveals the second banner, and `BootProbe` clears
          that timer as soon as any client component mounts.
        */}
        <noscript>
          <div className="border-b border-border bg-surface-2 px-4 py-2 text-center text-sm">
            JavaScript imezimwa / is turned off — content is still readable.
          </div>
        </noscript>
        {/*
          Server-rendered, because the case it reports is "the client bundle
          never arrived" — a component could not draw it. The reload control is
          therefore a native handler rather than a React one, for the same
          reason.
        */}
        <div
          id="weave-boot-warning"
          hidden
          className="border-b border-warn bg-warn-soft px-4 py-2 text-center text-sm text-warn"
          dangerouslySetInnerHTML={{
            __html:
              "Programu haijapakia kikamilifu / the app did not finish loading — " +
              '<button type="button" onclick="location.reload()" ' +
              'style="text-decoration:underline;text-underline-offset:2px">' +
              "jaribu tena / reload</button>",
          }}
        />
        <BootProbe />
        <AppShell language={language} authed={authed} theme={theme}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
