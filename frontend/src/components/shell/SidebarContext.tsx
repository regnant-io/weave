"use client";

import { createContext, useContext, useEffect, useState } from "react";

export interface ProjectMeta {
  id: string;
  title: string;
  mode: string;
}

interface Ctx {
  collapsed: boolean;
  toggle: () => void;
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
  project: ProjectMeta | null;
  setProject: (p: ProjectMeta | null) => void;
}

const SidebarCtx = createContext<Ctx | null>(null);

export function useSidebar() {
  const c = useContext(SidebarCtx);
  if (!c) throw new Error("useSidebar outside provider");
  return c;
}

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [project, setProject] = useState<ProjectMeta | null>(null);

  useEffect(() => {
    setCollapsed(localStorage.getItem("weave_sidebar_collapsed") === "1");
  }, []);

  function toggle() {
    setCollapsed((v) => {
      const nv = !v;
      localStorage.setItem("weave_sidebar_collapsed", nv ? "1" : "0");
      return nv;
    });
  }

  return (
    <SidebarCtx.Provider value={{ collapsed, toggle, mobileOpen, setMobileOpen, project, setProject }}>
      {children}
    </SidebarCtx.Provider>
  );
}

/** Rendered by the chat page to publish the current project into the sidebar. */
export function SetSidebarProject({ project }: { project: ProjectMeta }) {
  const { setProject } = useSidebar();
  useEffect(() => {
    setProject(project);
    return () => setProject(null);
  }, [project.id, project.title, project.mode]); // eslint-disable-line
  return null;
}
