export type Page = "chat" | "style" | "matches" | "profile" | "contact";
export type Message = { role?: string; content?: string; quality?: string; created_at?: string; delivery_status?: string };
export type Conversation = {
  id: string;
  status?: string;
  agent_name?: string | null;
  agent_model?: string | null;
  agent_tone?: string;
  messages: Message[];
};
export type MessageRecovery = {
  conversation_id: string;
  after_sequence: number;
  latest_sequence: number;
  messages: Array<{ message_index: number; message: Message }>;
};
export type ConversationSummary = {
  id: string;
  agent_name?: string | null;
  message_count?: number;
  context_source_count?: number;
  updated_at?: string | null;
};
export type AuthUser = { email?: string | null; display_name?: string | null; avatar_url?: string | null };
export type Profile = {
  display_name?: string;
  age?: number;
  gender?: string;
  interested_in?: string;
  city?: string;
  phone?: string;
  profile_photo_url?: string;
  profile_photo_urls?: string[];
};
export type ContextSource = {
  id: string;
  title?: string;
  source_type?: string;
  preview?: string;
  content_length?: number;
  attached?: boolean;
};
export type DataRequest = {
  id: string;
  request_type?: string;
  status?: string;
  message?: string;
  created_at?: string;
};
export type ProfileFact = {
  id: string;
  label?: string;
  key?: string;
  category?: string;
  value?: Record<string, unknown>;
  confidence?: number;
  fact_type?: string;
  confidence_state?: string;
  status?: string;
  evidence?: unknown[];
  source_kind?: string;
  source_id?: string | null;
  visibility?: string;
  used_for_matching?: boolean;
  used_for_chat_context?: boolean;
  feedback?: {
    rating?: string;
    reason?: string;
    comment?: string;
    updated_at?: string;
  } | null;
};
export type CanonicalMemory = {
  id: string;
  kind: "semantic" | "episodic" | "relationship" | "procedural";
  purposes?: string[];
  key: string;
  value: unknown;
  allowed_uses?: string[];
  status?: string;
  sensitivity?: string;
  confidence?: number;
  importance?: number;
  occurred_at?: string | null;
  valid_until?: string | null;
  updated_at?: string | null;
  feedback?: {
    rating?: "agree" | "disagree";
    reason?: string | null;
    comment?: string | null;
    review_count?: number;
    created_at?: string;
    updated_at?: string;
  } | null;
  evidence?: Array<{
    conversation_id?: string;
    message_id?: string | null;
    message_index?: number | null;
    exact_quote?: string;
    observed_at?: string;
  }>;
};
export type MemoryResponse = { count?: number; memories?: CanonicalMemory[] };

export type ProfileResponse = {
  user?: AuthUser;
  profile?: Profile;
  profile_photo_max_count?: number;
  memory_sources?: ContextSource[];
  style_sources?: ContextSource[];
  learned_facts?: ProfileFact[];
  learned_fact_groups?: Record<string, ProfileFact[]>;
  data_requests?: DataRequest[];
};
export type UsageSummary = {
  request_count?: number;
  successful_request_count?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated_cost_usd?: number;
  estimated_cost_inr?: number;
  average_tokens_per_message?: number;
  average_prompt_tokens_per_message?: number;
  average_completion_tokens_per_message?: number;
};
export type UsageEvent = {
  request_kind?: string;
  provider?: string;
  model?: string;
  created_at?: string;
  success?: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  result_summary?: {
    status?: string;
    memory_operations?: number;
    memories_applied?: number;
    memories_deferred?: number;
    thread_operations_applied?: number;
  };
};
export type ConversationUsage = {
  summary?: UsageSummary;
  events?: UsageEvent[];
};
