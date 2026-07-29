/**
 * The model list, in ONE canonical shape.
 *
 * `/api/v1/models` returns `[{name, context, trained_context}]`. An older build
 * returned `string[]`. Both shapes have been live, and a component that assumed
 * the string form rendered a raw object as a React child — which is exactly the
 * minified React error #31 (`object with keys {name, context}`) that took the
 * settings page down. Parsing happens here, once, so no component ever touches
 * the wire format again.
 */

export interface ModelInfo {
  name: string;
  /** Context window we will actually request, in tokens. */
  context?: number;
  /** What the model itself advertises (may exceed `context` if a ceiling is set). */
  trainedContext?: number;
}

export interface ModelCatalog {
  models: ModelInfo[];
  currentModel: string;
  engine: string;
  /** Window used when a model's own context can't be read. */
  fallbackContext: number;
  /** Opt-in ceiling; 0 means every model gets its full window. */
  ceiling: number;
}

const toInt = (v: unknown): number | undefined => {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.floor(n) : undefined;
};

/** Normalise one entry from either wire shape. Returns null for unusable input. */
export function parseModel(raw: unknown): ModelInfo | null {
  if (typeof raw === "string") return raw.trim() ? { name: raw.trim() } : null;
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const name = typeof o.name === "string" ? o.name.trim() : "";
  if (!name) return null;
  return {
    name,
    context: toInt(o.context),
    trainedContext: toInt(o.trained_context),
  };
}

export function parseCatalog(raw: unknown): ModelCatalog {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const list = Array.isArray(o.models) ? o.models : [];
  const models = list.map(parseModel).filter((m): m is ModelInfo => m !== null);
  return {
    models,
    currentModel:
      typeof o.current_model === "string" && o.current_model ? o.current_model : models[0]?.name ?? "",
    engine: typeof o.engine === "string" ? o.engine : "offline",
    fallbackContext: toInt(o.num_ctx_fallback) ?? 8192,
    ceiling: toInt(o.num_ctx_ceiling) ?? 0,
  };
}

/** Fetch + normalise. Never throws — an unreachable Ollama yields an empty catalog. */
export async function fetchCatalog(signal?: AbortSignal): Promise<ModelCatalog> {
  try {
    const res = await fetch("/api/models", { signal });
    if (!res.ok) return parseCatalog(null);
    return parseCatalog(await res.json());
  } catch {
    return parseCatalog(null);
  }
}

/** "128k", "8.2k", "512" — compact, never a bare token count in the UI. */
export function formatTokens(n: number | undefined | null): string {
  if (!n || n <= 0) return "—";
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1000) return `${Math.round(n / 100) / 10}k`;
  return String(n);
}

/**
 * The window to draw the meter against for a given selection.
 * Falls back to the catalog default so the meter never silently disappears.
 */
export function contextFor(catalog: ModelCatalog, model: string): number {
  return catalog.models.find((m) => m.name === model)?.context ?? catalog.fallbackContext;
}
