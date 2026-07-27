// Server-side API client. Runs only in Server Components / Route Handlers, so the
// httpOnly auth cookie is attached here and never exposed to client JS.
import "server-only";
import { getToken } from "./session";
import type { Dataset, Message, Project, SourcePassage, User } from "./types";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";
const PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  auth = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (auth) {
    const token = await getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_BASE}${PREFIX}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  base: API_BASE,
  prefix: PREFIX,

  me: () => request<User>("/auth/me"),

  health: async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
      const data = await res.json();
      return {
        llm_engine: data.llm_engine,
        embedding_backend: data.embedding_backend,
        sandbox_backend: data.sandbox_backend,
        database: data.database,
        tools: data.tools,
        capabilities: data.capabilities,
      };
    } catch {
      return null;
    }
  },

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (title: string, mode: string) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify({ title, mode }) }),
  getMessages: (id: string) => request<Message[]>(`/projects/${id}/messages`),

  getDatasetProfile: (id: string) => request<Dataset>(`/datasets/${id}/profile`),
  listProjectDatasets: (projectId: string) =>
    request<Dataset[]>(`/projects/${projectId}/datasets`),

  searchLibrary: (q: string, language: string, source?: string) => {
    const params = new URLSearchParams({ q, language });
    if (source) params.set("source", source);
    return request<{ query: string; language: string; results: SourcePassage[] }>(
      `/library/search?${params.toString()}`,
      {},
      false,
    );
  },
  listSources: () =>
    request<
      Array<{
        id: string;
        title: string;
        url: string | null;
        source_type: string;
        access_status: string;
        language: string;
        predatory_flag: boolean;
        publication_date: string | null;
      }>
    >("/library/sources", {}, false),
};

export { API_BASE, PREFIX };
