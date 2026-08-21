export type AccountRole = "user" | "librarian" | "research_admin" | "service_worker";
export type ConsentScope = "DECLARED_PROFILE" | "BEHAVIOR_LEARNING" | "PERSONALIZED_RECOMMENDATION" | "RESEARCH_ANALYTICS";

export interface IdentityAccount {
  user_id: number;
  account_uuid: string;
  display_name: string;
  status: string;
  roles: AccountRole[];
  must_change_password: boolean;
}

export interface LoginResult {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  user: IdentityAccount;
  personalization_consents: Record<ConsentScope, boolean>;
}

export interface MeResult {
  user: IdentityAccount;
  permissions: string[];
  personalization_consents: Record<ConsentScope, boolean>;
  session_uuid: string;
}

const roles = new Set<AccountRole>(["user", "librarian", "research_admin", "service_worker"]);
const scopes: ConsentScope[] = ["DECLARED_PROFILE", "BEHAVIOR_LEARNING", "PERSONALIZED_RECOMMENDATION", "RESEARCH_ANALYTICS"];
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

export function decodeIdentityAccount(value: unknown): IdentityAccount {
  if (!record(value) || typeof value.user_id !== "number" || !Number.isInteger(value.user_id) || value.user_id < 1 ||
      typeof value.account_uuid !== "string" || typeof value.display_name !== "string" || typeof value.status !== "string" ||
      !Array.isArray(value.roles) || !value.roles.every((role): role is AccountRole => typeof role === "string" && roles.has(role as AccountRole)) ||
      typeof value.must_change_password !== "boolean") throw new Error("INVALID_IDENTITY_ACCOUNT");
  return value as unknown as IdentityAccount;
}

function consents(value: unknown): Record<ConsentScope, boolean> {
  if (!record(value) || !scopes.every((scope) => typeof value[scope] === "boolean")) throw new Error("INVALID_IDENTITY_CONSENTS");
  return Object.fromEntries(scopes.map((scope) => [scope, Boolean(value[scope])])) as Record<ConsentScope, boolean>;
}

export function decodeLoginResult(value: unknown): LoginResult {
  if (!record(value) || typeof value.access_token !== "string" || value.token_type !== "Bearer" ||
      typeof value.expires_in !== "number" || value.expires_in < 60) throw new Error("INVALID_LOGIN_RESPONSE");
  return { access_token: value.access_token, token_type: "Bearer", expires_in: value.expires_in, user: decodeIdentityAccount(value.user), personalization_consents: consents(value.personalization_consents) };
}

export function decodeMeResult(value: unknown): MeResult {
  if (!record(value) || !Array.isArray(value.permissions) || !value.permissions.every((item) => typeof item === "string") || typeof value.session_uuid !== "string") throw new Error("INVALID_ME_RESPONSE");
  return { user: decodeIdentityAccount(value.user), permissions: value.permissions, personalization_consents: consents(value.personalization_consents), session_uuid: value.session_uuid };
}

export { scopes as consentScopes };
