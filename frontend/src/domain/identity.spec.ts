import { describe, expect, it } from "vitest";

import { decodeIdentityAccount, decodeLoginResult, decodeMeResult } from "./identity";

const user = {
  user_id: 10000,
  account_uuid: "2fd7afcc-1617-4f10-8e80-c7b7a80c2e90",
  display_name: "测试读者",
  status: "ACTIVE",
  roles: ["user"],
  must_change_password: false,
};
const consents = {
  DECLARED_PROFILE: true,
  BEHAVIOR_LEARNING: false,
  PERSONALIZED_RECOMMENDATION: true,
  RESEARCH_ANALYTICS: false,
};

describe("identity public contract", () => {
  it("strictly decodes login and current-session payloads", () => {
    expect(decodeLoginResult({ access_token: "jwt", token_type: "Bearer", expires_in: 600, user, personalization_consents: consents }).user.user_id).toBe(10000);
    expect(decodeMeResult({ user, permissions: ["catalog.read"], personalization_consents: consents, session_uuid: "session-1" }).permissions).toEqual(["catalog.read"]);
  });

  it("rejects unknown roles and incomplete consent maps", () => {
    expect(() => decodeIdentityAccount({ ...user, roles: ["superuser"] })).toThrow("INVALID_IDENTITY_ACCOUNT");
    expect(() => decodeLoginResult({ access_token: "jwt", token_type: "Bearer", expires_in: 600, user, personalization_consents: { DECLARED_PROFILE: true } })).toThrow("INVALID_IDENTITY_CONSENTS");
  });
});
