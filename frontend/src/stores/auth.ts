import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { identityClient, IdentityApiError } from "../api/identityClient";
import type { RequestIdentity } from "../api/authHeaders";
import type { ConsentScope, IdentityAccount } from "../domain/identity";
import { useSessionStore } from "./session";

export const useAuthStore = defineStore("auth", () => {
  const session = useSessionStore();
  const accessToken = ref("");
  const account = ref<IdentityAccount | null>(null);
  const permissions = ref<string[]>([]);
  const consents = ref<Record<ConsentScope, boolean> | null>(null);
  const phase = ref<"guest" | "restoring" | "authenticating" | "authenticated">("guest");
  const ready = ref(false);
  const dialogOpen = ref(false);
  const onboardingOpen = ref(false);
  const requestedFeature = ref("");
  const error = ref("");
  const researchDemoEnabled = String(import.meta.env.VITE_RESEARCH_DEMO_ENABLED ?? "false").toLowerCase() === "true";
  let refreshTimer: number | undefined;

  const authenticated = computed(() => phase.value === "authenticated" && account.value !== null && accessToken.value.length > 0);
  const requestIdentity = computed<RequestIdentity>(() => {
    if (authenticated.value) return { mode: "authenticated", accessToken: accessToken.value };
    if (session.mode === "demo" && researchDemoEnabled) return { mode: "demo", demoUserId: session.userId };
    return { mode: "guest" };
  });
  const canUsePersonalization = computed(() => Boolean(consents.value?.PERSONALIZED_RECOMMENDATION));
  const canPersistBehavior = computed(() => session.mode === "demo" || Boolean(consents.value?.BEHAVIOR_LEARNING));

  function scheduleRefresh(expiresIn: number): void {
    if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => { void refresh(); }, Math.max(30, expiresIn - 60) * 1000);
  }
  function acceptLogin(result: Awaited<ReturnType<typeof identityClient.login>>): void {
    const identityChanged = session.mode !== "authenticated" || session.userId !== result.user.user_id;
    accessToken.value = result.access_token;
    account.value = result.user;
    consents.value = result.personalization_consents;
    phase.value = "authenticated";
    error.value = "";
    dialogOpen.value = false;
    if (identityChanged) session.setAuthenticated(result.user.user_id);
    else session.touch();
    scheduleRefresh(result.expires_in);
    onboardingOpen.value = !result.user.must_change_password && Object.values(result.personalization_consents).every((value) => !value);
    if (result.user.must_change_password) dialogOpen.value = true;
  }
  async function restore(): Promise<void> {
    if (ready.value || authenticated.value) return;
    phase.value = "restoring";
    try { acceptLogin(await identityClient.refresh()); await loadMe(); }
    catch { clearLocal(); }
    finally { ready.value = true; }
  }
  async function login(identifierType: "READER_NUMBER" | "STUDENT_NUMBER", identifier: string, password: string): Promise<void> {
    phase.value = "authenticating"; error.value = "";
    try { acceptLogin(await identityClient.login(identifierType, identifier, password)); await loadMe(); ready.value = true; }
    catch (caught) { phase.value = "guest"; error.value = caught instanceof IdentityApiError ? "证号或密码不正确，请检查后重试。" : "登录服务暂时不可用。"; throw caught; }
  }
  async function refresh(): Promise<boolean> {
    try { acceptLogin(await identityClient.refresh()); await loadMe(); return true; }
    catch { clearLocal(); return false; }
  }
  async function logout(): Promise<void> {
    const token = accessToken.value;
    try { if (token) await identityClient.logout(token); }
    finally { clearLocal(); }
  }
  function clearLocal(): void {
    const identityChanged = session.mode === "authenticated";
    if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    refreshTimer = undefined; accessToken.value = ""; account.value = null; permissions.value = []; consents.value = null;
    phase.value = "guest"; onboardingOpen.value = false;
    if (identityChanged) session.reset(); else session.setGuest();
  }
  function requireLogin(feature = "此功能"): boolean {
    if (authenticated.value || (researchDemoEnabled && session.mode === "demo")) return true;
    requestedFeature.value = feature; dialogOpen.value = true; return false;
  }
  async function loadMe(): Promise<void> {
    if (!accessToken.value) return;
    const result = await identityClient.me(accessToken.value);
    account.value = result.user; permissions.value = result.permissions; consents.value = result.personalization_consents;
  }
  async function setConsent(scope: ConsentScope, granted: boolean, source: "LOGIN_ONBOARDING" | "SETTINGS" = "SETTINGS"): Promise<void> {
    if (!accessToken.value) throw new Error("AUTH_REQUIRED");
    consents.value = await identityClient.consent(accessToken.value, scope, granted ? "GRANT" : "WITHDRAW", source);
    await loadMe();
  }
  async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    if (!accessToken.value) throw new Error("AUTH_REQUIRED");
    await identityClient.changePassword(accessToken.value, currentPassword, newPassword);
    clearLocal();
    requestedFeature.value = "密码已更新，请使用新密码重新登录";
    dialogOpen.value = true;
  }
  function useResearchDemo(): void { if (researchDemoEnabled) { clearLocal(); session.setMode("demo"); } }

  return { accessToken, account, permissions, consents, phase, ready, dialogOpen, onboardingOpen, requestedFeature, error, researchDemoEnabled, authenticated, requestIdentity, canUsePersonalization, canPersistBehavior, restore, login, refresh, logout, clearLocal, requireLogin, loadMe, setConsent, changePassword, useResearchDemo };
});
