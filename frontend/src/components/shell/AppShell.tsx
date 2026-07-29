"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ThemePref } from "@/lib/session";
import type { Language } from "@/lib/types";
import WeaveMark from "@/components/brand/WeaveMark";
import { IcoMenu, IcoPanelLeft } from "@/components/ui/icons";
import Sidebar from "./Sidebar";
import { SidebarProvider, useSidebar } from "./SidebarContext";
import { useViewportInsets } from "./useViewportInsets";

export default function AppShell({
  language,
  authed,
  theme,
  children,
}: {
  language: Language;
  authed: boolean;
  theme: ThemePref;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  // Onboarding owns the whole viewport, chrome included: the rail would offer
  // navigation to places the user has not set up yet, and the header wordmark
  // would collide with the one the onboarding flow draws itself.
  const isOnboarding = pathname.startsWith("/onboarding");
  if (isOnboarding) return <>{children}</>;

  if (!authed) {
    return (
      <div className="min-h-app flex flex-col overflow-x-hidden">
        <header className="flex h-16 flex-shrink-0 items-center px-5 md:px-8">
          <Link href="/" aria-label="Weave" className="text-fg transition-opacity hover:opacity-70">
            <WeaveMark size="sm" />
          </Link>
        </header>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    );
  }

  return (
    <SidebarProvider>
      <Frame language={language} authed={authed} theme={theme}>
        {children}
      </Frame>
    </SidebarProvider>
  );
}

function Frame({
  language,
  authed,
  theme,
  children,
}: {
  language: Language;
  authed: boolean;
  theme: ThemePref;
  children: React.ReactNode;
}) {
  const { collapsed, toggle, setMobileOpen } = useSidebar();
  // Publishes --kb-inset so bottom-anchored UI can clear the iOS keyboard.
  useViewportInsets();

  return (
    <div className="h-app flex overflow-hidden">
      <Sidebar language={language} authed={authed} theme={theme} />
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/*
          Mobile has NO top bar — the content owns the whole viewport. Navigation
          is a single floating button, so the reading surface stays clean.
          Desktop gets the same treatment when the rail is fully hidden: a small
          reveal affordance instead of a permanent 68px stub.
        */}
        {/* The floating controls sit ABOVE the content plane, so every page pads
            itself by --chrome-top (see .pad-chrome-top) rather than each one
            guessing an offset. Top is safe-area aware for notched devices. */}
        <button
          onClick={() => setMobileOpen(true)}
          aria-label={language === "sw" ? "Fungua menyu" : "Open menu"}
          style={{ top: "calc(0.75rem + var(--safe-top))" }}
          className="fixed left-3 z-30 grid h-10 w-10 place-items-center rounded-full border border-border bg-surface/85 text-fg-muted shadow-soft backdrop-blur transition-all duration-fast ease-soft hover:text-fg active:scale-95 md:hidden"
        >
          <IcoMenu />
        </button>

        {collapsed && (
          <button
            onClick={toggle}
            aria-label={language === "sw" ? "Onyesha kando" : "Show sidebar"}
            style={{ top: "calc(0.75rem + var(--safe-top))" }}
            className="animate-fade fixed left-3 z-30 hidden h-9 w-9 place-items-center rounded-full border border-border bg-surface/85 text-fg-faint shadow-soft backdrop-blur transition-all duration-fast ease-soft hover:text-fg md:grid"
          >
            <IcoPanelLeft />
          </button>
        )}

        <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
