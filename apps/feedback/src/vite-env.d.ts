/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FEEDBACK_SUBMISSION_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
