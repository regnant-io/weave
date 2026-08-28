export type Language = "sw" | "en";
export type Mode = "student" | "researcher";

export interface User {
  id: string;
  phone: string | null;
  email: string | null;
  role: string;
  preferred_language: Language;
  trust_tier: string;
  phone_verified: boolean;
  institution_id: string | null;
}

export interface Project {
  id: string;
  title: string;
  mode: Mode;
  hypotheses: Array<Record<string, unknown>>;
  notes?: Array<{ id: string; text: string; created_at: string }>;
  summary: string;
  created_at: string;
}

export interface Citation {
  source_id: string | null;
  title: string | null;
  url: string | null;
  source_type: string | null;
  access_status: string | null;
  predatory_flag: boolean | null;
}

/**
 * One persisted step of a turn's tool work.
 *
 * This is the stored form of what the SSE stream rendered live, written by
 * `_step_timeline` on the server. Reloading a conversation replays these, so a
 * refresh no longer discards every tool panel. `name` is retained because the
 * stats endpoint counts tool usage from the same column.
 */
export interface ToolCall {
  name: string;
  status?: string;
  output_files?: Array<{ name: string; s3_key: string; mime: string; bytes: number }>;
  id?: string;
  tool?: string;
  title?: string;
  args?: Record<string, unknown>;
  state?: "running" | "done" | "error";
  summary?: string;
  detail?: string;
  error?: string;
  substeps?: Array<{ text: string; url?: string; detail?: string; state?: string }>;
  artifacts?: Artifact[];
  /** Outcome of opening this step's artifact in a real browser. */
  verification?: {
    ok: boolean;
    attempt?: number;
    errors?: string[];
    warnings?: string[];
    summary?: string;
  };
}

export interface Artifact {
  name: string;
  mime: string;
  bytes: number;
  tool?: string;
  url: string;
  /**
   * Whether the page was opened in a real browser and rendered without errors.
   * `false` means it was released with known defects after the repair budget ran
   * out — the user is being shown something that does not fully work, and the UI
   * has to say so rather than presenting it like everything else.
   * `undefined` means it was never gated (a chart rendered server-side to SVG).
   */
  verified?: boolean;
  /** What still fails, when `verified` is false. */
  defects?: string[];
  /**
   * JPEG screenshot captured during verification. Used as the poster frame for
   * heavy embeds so a transcript with a dozen 3D scenes does not need a dozen
   * live WebGL contexts — browsers cap those, and the early ones get killed.
   */
  preview?: string;
}

/** One step of the plan the assistant committed to at the start of a turn. */
export interface PlanStep {
  n: number;
  title: string;
  status: "pending" | "active" | "done" | "failed" | "skipped";
  note?: string;
}

/**
 * The ledger the supervised loop works to.
 *
 * Present only on turns that were planned — a greeting is not planned, and
 * showing an empty plan rail on every reply would train people to ignore it.
 */
export interface Plan {
  goal?: string;
  steps: PlanStep[];
  checks?: string[];
}

export interface WebImage {
  url: string;
  title?: string;
  source?: string;
}

export type Effort = "spool" | "weave" | "tapestry";

/** One conversation inside a project. */
export interface Thread {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  status: "active" | "archived" | "rolled";
  parent_thread_id: string | null;
  token_estimate: number;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** A fact the assistant carries across every chat in a project. */
export interface MemoryEntry {
  id: string;
  key: string;
  content: string;
  kind: "fact" | "decision" | "preference" | "finding" | "question" | "artifact";
  importance: number;
  thread_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface UsageStats {
  projects: number;
  sessions: number;
  messages: number;
  prompts: number;
  total_tokens: number;
  active_days: number;
  current_streak: number;
  longest_streak: number;
  peak_hour: number | null;
  busiest_weekday: number | null;
  favourite_model: string;
  datasets: number;
  analyses: number;
  top_tools: Array<{ name: string; count: number }>;
  last_active: string | null;
  activity: Array<{ date: string; active: boolean }>;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content_sw: string;
  content_en: string;
  original_language: Language;
  tool_calls: ToolCall[];
  citations: Citation[];
  artifacts?: Artifact[];
  images?: WebImage[];
  /** The plan this turn worked to; `{}` for turns that did not need one. */
  plan?: Plan | Record<string, never>;
  created_at: string;
}

export interface DatasetProfileColumn {
  name: string;
  dtype: string;
  kind: string;
  non_null: number;
  null: number;
  unique: number;
  stats?: Record<string, number | null>;
  top_values?: Array<{ value: string; count: number }>;
}

export interface Dataset {
  id: string;
  original_filename: string;
  row_count: number | null;
  size_bytes: number;
  status: string;
  uploaded_at: string;
  column_profile: {
    available?: boolean;
    row_count?: number;
    column_count?: number;
    columns?: DatasetProfileColumn[];
    reason?: string;
  };
}

export interface SourcePassage {
  source_id: string;
  chunk_id: string;
  title: string;
  url: string | null;
  source_type: string;
  access_status: string;
  language: string;
  predatory_flag: boolean;
  content: string;
  score: number;
}
