export type IdentityMode = "guest" | "demo" | "authenticated";

export interface RequestIdentity {
  mode: IdentityMode;
  accessToken?: string;
  demoUserId?: number;
}

export function identityHeaders(identity: RequestIdentity): Record<string, string> {
  if (identity.mode === "authenticated") {
    if (!identity.accessToken) throw new Error("AUTH_ACCESS_TOKEN_REQUIRED");
    return { Authorization: `Bearer ${identity.accessToken}` };
  }
  if (identity.mode === "demo") {
    if (!Number.isInteger(identity.demoUserId) || Number(identity.demoUserId) < 1) {
      throw new Error("DEMO_USER_ID_REQUIRED");
    }
    return { "X-Demo-User-Id": String(identity.demoUserId) };
  }
  return {};
}
