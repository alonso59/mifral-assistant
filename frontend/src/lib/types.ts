export type GenerationProvider = 'anthropic' | 'openai' | 'google' | 'ollama' | 'openrouter';
export type EmbeddingProvider = 'sentence-transformers' | 'openai' | 'google' | 'ollama';

export interface Chat {
  id: string;
  session_id: string;
  title: string;
  knowledge_space_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  id: string;
  title: string;
  excerpt: string;
  section?: string | null;
  page?: number | null;
}

export interface ChatMessage {
  id: string;
  role: 'USER' | 'ASSISTANT';
  content: string;
  grounded: boolean;
  citations: Citation[];
  feedback_vote?: 'LIKE' | 'DISLIKE' | null;
  created_at: string;
  thinking?: boolean;
  thinkingText?: string;
  thoughtsExpanded?: boolean;
  streaming?: boolean;
}

export interface KnowledgeDocument {
  id: string;
  filename: string;
  processing_status: 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';
  processing_stage: 'QUEUED' | 'EXTRACTING' | 'CHUNKING' | 'EMBEDDING' | 'FINALIZING' | 'READY' | 'FAILED';
  processing_progress_percent: number;
  processing_message: string | null;
  chunk_count: number;
  created_at: string;
}

export interface KnowledgeSpace {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  documents: KnowledgeDocument[];
}

export interface ProviderOption {
  id: string;
  label: string;
  hint: string;
  default_model: string;
}

export interface ProviderModelOption {
  id: string;
  label: string;
  supports_reasoning: boolean;
}

export interface GenerationSettings {
  provider: GenerationProvider;
  model: string;
  api_key_set: boolean;
  base_url: string | null;
  system_prompt: string | null;
  temperature: number;
  max_tokens: number;
  context_max_tokens: number;
  auto_compress: boolean;
}

export interface EmbeddingSettings {
  provider: EmbeddingProvider;
  model: string;
  api_key_set: boolean;
  base_url: string | null;
}

export interface ModelSettings {
  generation: GenerationSettings;
  embedding: EmbeddingSettings;
  generation_provider_options: ProviderOption[];
  embedding_provider_options: ProviderOption[];
}

export interface UpdateGenerationSettings {
  provider: GenerationProvider;
  model: string;
  api_key?: string | null;
  base_url?: string | null;
  system_prompt?: string | null;
  temperature: number;
  max_tokens: number;
  context_max_tokens: number;
  auto_compress: boolean;
}

export interface UpdateEmbeddingSettings {
  provider: EmbeddingProvider;
  model: string;
  api_key?: string | null;
  base_url?: string | null;
}

export interface UpdateModelSettings {
  generation: UpdateGenerationSettings;
  embedding: UpdateEmbeddingSettings;
}

export interface KnowledgeSettings {
  chunk_size: number;
  chunk_overlap: number;
  retrieval_top_k: number;
  relevance_threshold: number;
  enable_markdown_chunking: boolean;
  query_augmentation: boolean;
  hybrid_search_enabled: boolean;
  hybrid_bm25_weight: number;
  rag_template: string;
}

export interface SystemSettings {
  app_name: string;
  theme: 'light' | 'dark' | 'system';
  show_thinking_overlay: boolean;
}

export interface OllamaModel {
  name: string;
  size?: number;
  modified_at?: string;
}

export interface OllamaHealth {
  ok: boolean;
  model_count: number;
}
