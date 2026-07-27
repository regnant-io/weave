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

export interface ToolCall {
  name: string;
  status?: string;
  output_files?: Array<{ name: string; s3_key: string; mime: string; bytes: number }>;
}

export interface Artifact {
  name: string;
  mime: string;
  bytes: number;
  tool?: string;
  url: string;
}

export interface WebImage {
  url: string;
  title?: string;
  source?: string;
}

export type Effort = "spool" | "weave" | "tapestry";

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
