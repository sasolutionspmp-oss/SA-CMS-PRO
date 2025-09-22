/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_DEV_TOKEN?: string;
  readonly VITE_PROXY_TARGET?: string;
  readonly VITE_TAILWIND_PROBE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
