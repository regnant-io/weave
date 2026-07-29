import type { Artifact, Citation, WebImage } from "./types";

/**
 * The chat message model is a BLOCK TIMELINE, not a message with a steps-box.
 *
 * A turn is an ordered list of blocks. The assistant narrates (text block), does
 * work (step block), narrates again, does more work — exactly the shape of a
 * real agentic run. This is what lets tool activity interleave with prose
 * instead of piling into one panel above the answer, and it is what makes an
 * hours-long run auditable: every step keeps its own collapsed record.
 */

export type StepState = "running" | "done" | "error" | "skipped";

export interface Substep {
  id: string;
  /** Human-readable line: "Read nbs.go.tz/report.pdf". */
  text: string;
  /** Optional link target — sources, artifacts, pages read. */
  url?: string;
  state: StepState;
  /** Monospace detail shown when the substep itself is expanded (stdout, SQL, ...). */
  detail?: string;
}

/** An artifact announced before it exists, so the UI can reserve shaped space. */
export type PendingKind =
  | "chart"
  | "document"
  | "visual"
  | "diagram"
  | "simulation"
  | "animation"
  | "analysis";

export interface PendingArtifact {
  id: string;
  kind: PendingKind;
  tool?: string;
  title?: string;
  /** Set when the producing tool finished — the skeleton stops shimmering. */
  resolved?: boolean;
  /** Resolved but produced nothing: show a quiet failure note, not a spinner. */
  failed?: boolean;
}

export interface StepBlock {
  kind: "step";
  id: string;
  /** Tool that produced this step, when it came from one. */
  tool?: string;
  /** Arguments the tool was called with (already truncated by the server). */
  args?: Record<string, unknown>;
  /**
   * Plain-text record of what the tool actually did — stdout, result titles,
   * SQL, files written. Most tools emit no incremental substeps, so this is
   * what makes an expanded step worth opening.
   */
  detail?: string;
  /** Artifacts still being produced by this step. */
  pending: PendingArtifact[];
  /**
   * Deterministic title from tool+args, upgraded in place if the model supplies
   * an authored one. Never blank, never late.
   */
  title: string;
  state: StepState;
  substeps: Substep[];
  /** Artifacts produced inside this step (charts, decks, visuals). */
  artifacts: Artifact[];
  startedAt: number;
  endedAt?: number;
  /** One-line outcome shown on the collapsed chip ("3 charts", "12 pages"). */
  summary?: string;
  error?: string;
}

export interface TextBlock {
  kind: "text";
  id: string;
  text: string;
}

/** One question the assistant is blocking on. */
export interface AskUserQuestion {
  question: string;
  header?: string;
  options: { label: string; description?: string }[];
  multi_select?: boolean;
}

export interface AskUserRequest {
  id: string;
  questions: AskUserQuestion[];
  answered?: boolean;
}

/**
 * A blocking question, placed in the timeline where it was asked.
 *
 * It is a BLOCK rather than a floating modal on purpose: the question belongs to
 * the moment in the work that raised it, and a modal would hide the reasoning
 * that makes the question answerable.
 */
export interface AskBlock {
  kind: "ask";
  id: string;
  request: AskUserRequest;
}

/** Generated output rendered inline, in the order it was produced. */
export interface ArtifactBlock {
  kind: "artifact";
  id: string;
  artifact: Artifact;
}

export type Block = TextBlock | StepBlock | AskBlock | ArtifactBlock;

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  /** User turns use plain text; assistant turns use blocks. */
  text: string;
  blocks: Block[];
  thinking: string;
  citations: Citation[];
  images: WebImage[];
  artifacts: Artifact[];
  pending: boolean;
  error?: boolean;
  createdAt: number;
}

export const isStep = (b: Block): b is StepBlock => b.kind === "step";
export const isText = (b: Block): b is TextBlock => b.kind === "text";
export const isAsk = (b: Block): b is AskBlock => b.kind === "ask";
export const isArtifactBlock = (b: Block): b is ArtifactBlock => b.kind === "artifact";

/** Total text of an assistant turn (for copy, and for history round-trips). */
export function turnText(t: ChatTurn): string {
  if (t.role === "user") return t.text;
  return t.blocks
    .filter(isText)
    .map((b) => b.text)
    .join("\n\n")
    .trim();
}

/** Every artifact a turn produced, from its own list and from inside its steps. */
export function turnArtifacts(t: ChatTurn): Artifact[] {
  const out = [...t.artifacts];
  for (const b of t.blocks) {
    if (isStep(b)) out.push(...b.artifacts);
    else if (isArtifactBlock(b)) out.push(b.artifact);
  }
  const seen = new Set<string>();
  return out.filter((a) => (seen.has(a.url) ? false : (seen.add(a.url), true)));
}
