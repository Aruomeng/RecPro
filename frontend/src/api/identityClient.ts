import { decodeDeclaredProfileResult, decodeIdentityAccount, decodeLoginResult, decodeMeResult } from "../domain/identity";
import type { ConsentScope, DeclaredProfileResult, IdentityAccount, LoginResult, MeResult } from "../domain/identity";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class IdentityApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); this.name = "IdentityApiError"; }
}

function cookie(name: string): string {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) ?? "";
}

async function json(response: Response): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = typeof payload === "object" && payload !== null && "error" in payload ? (payload as { error?: { code?: string; message?: string } }).error : undefined;
    throw new IdentityApiError(response.status, error?.code ?? "IDENTITY_REQUEST_FAILED", error?.message ?? "身份服务暂时无法完成请求。");
  }
  return payload;
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  return json(await fetch(`${baseUrl}${path}`, { cache: "no-store", credentials: "include", ...init }));
}

const content = { Accept: "application/json", "Content-Type": "application/json" };

export const identityClient = {
  async login(identifierType: "READER_NUMBER" | "STUDENT_NUMBER", identifier: string, password: string): Promise<LoginResult> {
    return decodeLoginResult(await request("/api/v1/auth/login", { method: "POST", headers: content, body: JSON.stringify({ identifier_type: identifierType, identifier, password, device_type: "KIOSK" }) }));
  },
  async refresh(): Promise<LoginResult> {
    return decodeLoginResult(await request("/api/v1/auth/refresh", { method: "POST", headers: { ...content, "X-CSRF-Token": decodeURIComponent(cookie("recpro_csrf")) } }));
  },
  async me(accessToken: string): Promise<MeResult> {
    return decodeMeResult(await request("/api/v1/auth/me", { headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` } }));
  },
  async declaredProfile(accessToken: string): Promise<DeclaredProfileResult> {
    return decodeDeclaredProfileResult(await request("/api/v1/me/profile", { headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` } }));
  },
  async updateDeclaredProfile(accessToken: string, profile: { major: string | null; grade: string | null; research_direction: string | null; preferred_language: string | null }): Promise<DeclaredProfileResult> {
    return decodeDeclaredProfileResult(await request("/api/v1/me/declared-profile", {
      method: "PUT", headers: { ...content, Authorization: `Bearer ${accessToken}` }, body: JSON.stringify(profile),
    }));
  },
  async logout(accessToken: string): Promise<void> {
    const response = await fetch(`${baseUrl}/api/v1/auth/logout`, { method: "POST", credentials: "include", headers: { Authorization: `Bearer ${accessToken}` } });
    if (!response.ok && response.status !== 401) await json(response);
  },
  async activate(identifierType: "READER_NUMBER" | "STUDENT_NUMBER", identifier: string, activationCode: string, newPassword: string): Promise<IdentityAccount> {
    return decodeIdentityAccount(await request("/api/v1/auth/activate", { method: "POST", headers: content, body: JSON.stringify({ identifier_type: identifierType, identifier, activation_code: activationCode, new_password: newPassword }) }));
  },
  async completeReset(identifierType: "READER_NUMBER" | "STUDENT_NUMBER", identifier: string, resetCode: string, newPassword: string): Promise<IdentityAccount> {
    return decodeIdentityAccount(await request("/api/v1/auth/password-reset/complete", { method: "POST", headers: content, body: JSON.stringify({ identifier_type: identifierType, identifier, reset_code: resetCode, new_password: newPassword }) }));
  },
  async changePassword(accessToken: string, currentPassword: string, newPassword: string): Promise<IdentityAccount> {
    return decodeIdentityAccount(await request("/api/v1/auth/password/change", {
      method: "POST", headers: { ...content, Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }));
  },
  async consent(accessToken: string, scope: ConsentScope, action: "GRANT" | "WITHDRAW", source: "LOGIN_ONBOARDING" | "SETTINGS" = "SETTINGS"): Promise<Record<ConsentScope, boolean>> {
    const payload = await request("/api/v1/me/personalization-consents", { method: "POST", headers: { ...content, Authorization: `Bearer ${accessToken}` }, body: JSON.stringify({ scope, action, policy_version: "privacy-v1", source }) });
    if (typeof payload !== "object" || payload === null || !("personalization_consents" in payload)) throw new Error("INVALID_CONSENT_RESPONSE");
    return (payload as { personalization_consents: Record<ConsentScope, boolean> }).personalization_consents;
  },
};
