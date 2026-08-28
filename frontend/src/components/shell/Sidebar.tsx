"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ThemePref } from "@/lib/session";
import type { Language } from "@/lib/types";
import { t } from "@/lib/i18n";
import WeaveMark from "@/components/brand/WeaveMark";
import DatasetUpload from "@/components/DatasetUpload";
import {
  IcoClose,
  IcoDataset,
  IcoLibrary,
  IcoLogout,
  IcoMonitor,
  IcoMoon,
  IcoPanelClose,
  IcoProjects,
  IcoSettings,
  IcoSun,
} from "@/components/ui/icons";
import { useSidebar } from "./SidebarContext";

const order: ThemePref[] = ["light", "dark", "system"];

export default function Sidebar({
  language,
  authed,
  theme,
}: {
  language: Language;
  authed: boolean;
  theme: ThemePref;
}) {
  const { collapsed, toggle, mobileOpen, setMobileOpen, project } = useSidebar();
  const pathname = usePathname();
  const router = useRouter();
  const sw = language === "sw";

  async function setLang(l: Language) {
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: l }),
    });
    router.refresh();
  }

  function applyTheme(p: ThemePref) {
    const root = document.documentElement;
    if (p === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", p);
  }

  async function cycleTheme() {
    const cur = (document.cookie.match(/weave_theme=(\w+)/)?.[1] as ThemePref) || "system";
    const next = order[(order.indexOf(cur) + 1) % order.length];
    applyTheme(next);
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: next }),
    });
    router.refresh();
  }

  async function logout() {
    await fetch("/api/session/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  }

  const NavItem = ({ href, icon: Icon, label }: { href: string; icon: any; label: string }) => {
    const active = pathname === href || pathname.startsWith(href + "/");
    return (
      <Link
        href={href}
        onClick={() => setMobileOpen(false)}
        className={`group relative flex items-center gap-3 px-3 py-2 text-sm transition-colors duration-fast ease-soft ${
          active ? "text-fg" : "text-fg-muted hover:text-fg"
        }`}
      >
        {/* Active state is an editorial rule, not a filled pill. */}
        <span
          className={`absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 bg-accent transition-all duration-300 ease-expo ${
            active ? "opacity-100" : "scale-y-0 opacity-0"
          }`}
        />
        <Icon className="flex-shrink-0" />
        <span className="truncate">{label}</span>
      </Link>
    );
  };

  const ThemeIcon = theme === "light" ? IcoSun : theme === "dark" ? IcoMoon : IcoMonitor;

  return (
    <>
      {/* mobile scrim */}
      <div
        onClick={() => setMobileOpen(false)}
        className={`fixed inset-0 z-40 bg-black/45 transition-opacity duration-panel ease-expo md:hidden ${
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        /*
          Collapsing hides the rail COMPLETELY on desktop — width 0, no stub.
          The reveal affordance lives in AppShell as a floating button, so the
          content column gets the entire viewport when the user wants focus.
        */
        style={{ width: collapsed ? 0 : undefined }}
        className={`fixed inset-y-0 left-0 z-50 flex w-[268px] flex-col overflow-hidden border-r border-border bg-bg-subtle
          transition-transform duration-panel ease-expo
          md:static md:translate-x-0 md:transition-[width] md:duration-panel md:ease-expo
          ${collapsed ? "md:w-0 md:border-r-0" : "md:w-[268px]"}
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex h-full w-[268px] flex-col">
          {/* brand */}
          <div className="flex h-16 items-center gap-2 px-4">
            <Link
              href={authed ? "/app/projects" : "/"}
              className="min-w-0 text-fg transition-opacity duration-fast hover:opacity-70"
              aria-label="Weave"
            >
              <WeaveMark size="sm" animate={false} />
            </Link>
            <button
              onClick={toggle}
              className="ml-auto hidden h-8 w-8 items-center justify-center text-fg-faint transition-colors duration-fast hover:text-fg md:flex"
              title={sw ? "Ficha kando" : "Hide sidebar"}
            >
              <IcoPanelClose />
            </button>
            <button
              onClick={() => setMobileOpen(false)}
              className="ml-auto grid h-8 w-8 place-items-center text-fg-faint transition-colors duration-fast hover:text-fg md:hidden"
              aria-label={sw ? "Funga" : "Close"}
            >
              <IcoClose />
            </button>
          </div>

          <div className="mx-4 h-px bg-border" />

          {/* nav */}
          <nav className="flex flex-col gap-0.5 py-3 pl-1 pr-2">
            <NavItem href="/app/projects" icon={IcoProjects} label={t("projects", language)} />
            <NavItem href="/app/library" icon={IcoLibrary} label={t("library", language)} />
            <NavItem href="/app/settings" icon={IcoSettings} label={t("settings", language)} />
          </nav>

          {/* current project */}
          {project && (
            <div className="mx-4 border-t border-border pt-3">
              <div className="eyebrow mb-1">{sw ? "Mradi" : "Project"}</div>
              <div className="truncate text-sm font-medium">{project.title}</div>
              <div
                className={`mt-0.5 text-[11px] ${
                  project.mode === "researcher" ? "text-warn" : "text-accent"
                }`}
              >
                {project.mode === "researcher"
                  ? sw
                    ? "Mtafiti"
                    : "Researcher"
                  : sw
                    ? "Mwanafunzi"
                    : "Student"}
              </div>
              <div className="mt-2.5 flex items-center gap-3 text-xs">
                <DatasetUpload projectId={project.id} language={language} />
                <Link
                  href={`/app/projects/${project.id}`}
                  className="flex items-center gap-1.5 text-fg-muted transition-colors duration-fast hover:text-fg"
                >
                  <IcoDataset size={14} />
                  {sw ? "Kumbukumbu" : "Memory"}
                </Link>
              </div>
            </div>
          )}

          {/* bottom prefs */}
          <div className="mt-auto flex items-center gap-2 border-t border-border p-3">
            <div className="flex border border-border">
              {(["sw", "en"] as Language[]).map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-2 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors duration-fast ${
                    language === l ? "bg-fg text-bg" : "text-fg-muted hover:text-fg"
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
            <button
              onClick={cycleTheme}
              className="grid h-8 w-8 place-items-center text-fg-muted transition-colors duration-fast hover:text-fg"
              title={sw ? "Mandhari" : "Theme"}
            >
              <ThemeIcon />
            </button>
            {authed && (
              <button
                onClick={logout}
                className="ml-auto grid h-8 w-8 place-items-center text-fg-muted transition-colors duration-fast hover:text-danger"
                title={t("logout", language)}
              >
                <IcoLogout />
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
