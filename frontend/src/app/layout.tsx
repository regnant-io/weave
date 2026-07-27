import type { Metadata, Viewport } from "next";
import { Playfair_Display, Source_Serif_4, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { getLanguage, getTheme, isAuthed } from "@/lib/session";
import AppShell from "@/components/shell/AppShell";

/* Editorial type stack (design.md §Typography), self-hosted by next/font so
   there is no third-party request at runtime and no FOUT. Each exposes a CSS
   variable consumed by globals.css. */
const playfair = Playfair_Display({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-playfair",
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  fallback: ["Georgia", "Times New Roman", "serif"],
});
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-source-serif",
  weight: ["400", "600"],
  style: ["normal", "italic"],
  fallback: ["Georgia", "serif"],
});
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
  fallback: ["ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains",
  weight: ["400", "500"],
  fallback: ["ui-monospace", "Consolas", "monospace"],
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
  const fontVars = `${playfair.variable} ${sourceSerif.variable} ${inter.variable} ${jetbrains.variable}`;

  return (
    <html
      lang={language}
      className={`no-js ${fontVars}`}
      {...(htmlThemeAttr ? { "data-theme": htmlThemeAttr } : {})}
      /*
        The blocking script below intentionally mutates <html> before React
        hydrates: it drops `no-js` and stamps `data-theme` from the cookie so
        there is no flash of the wrong theme. That is precisely the server/client
        divergence React warns about, and it is correct here — the alternative is
        a visible flash on every load. Suppression is one level deep and does not
        affect any child.
      */
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "document.documentElement.classList.remove('no-js');" +
              "try{var m=document.cookie.match(/weave_theme=(light|dark)/);if(m){document.documentElement.setAttribute('data-theme',m[1]);}else{document.documentElement.removeAttribute('data-theme');}}catch(e){}" +
              "if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})});}",
          }}
        />
      </head>
      <body className="bg-bg text-fg">
        <div className="no-js-banner border-b border-border bg-surface-2 px-4 py-2 text-center text-sm">
          JavaScript haijapakia / did not load — content is still readable.
        </div>
        <AppShell language={language} authed={authed} theme={theme}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
