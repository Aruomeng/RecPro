/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_G4_DEMO_REQUEST_ID?: string;
  readonly VITE_G4_DEMO_SESSION_ID?: string;
  readonly VITE_G5_INTERACTION_ENABLED?: string;
  readonly VITE_RESEARCH_DEMO_ENABLED?: string;
  readonly VITE_KIOSK_GUEST_USER_ID?: string;
  readonly VITE_KIOSK_DEMO_USER_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
