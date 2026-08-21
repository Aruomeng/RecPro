import { computed, ref } from "vue";
import { defineStore } from "pinia";

const GUEST_USER_ID = Number(import.meta.env.VITE_KIOSK_GUEST_USER_ID ?? 9000001);
const DEMO_USER_ID = Number(import.meta.env.VITE_KIOSK_DEMO_USER_ID ?? 1001);

function uuid(): string {
  return globalThis.crypto?.randomUUID?.() ?? `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export const useSessionStore = defineStore("session", () => {
  const mode = ref<"guest" | "demo" | "authenticated">("guest");
  const authenticatedUserId = ref<number | null>(null);
  const sessionId = ref(uuid());
  const secondsRemaining = ref(120);
  const resetEpoch = ref(0);
  const inactivityEpoch = ref(0);
  const busy = ref(false);
  let timer: number | undefined;
  let started = false;

  const userId = computed(() => mode.value === "authenticated" ? (authenticatedUserId.value ?? GUEST_USER_ID) : mode.value === "demo" ? DEMO_USER_ID : GUEST_USER_ID);
  const showCountdown = computed(() => !busy.value && secondsRemaining.value <= 15);

  function limit(): number { return mode.value === "authenticated" ? 300 : 120; }
  function touch(): void { secondsRemaining.value = limit(); }
  function setMode(value: "guest" | "demo"): void { mode.value = value; authenticatedUserId.value = null; sessionId.value = uuid(); resetEpoch.value += 1; touch(); }
  function setAuthenticated(userId: number): void { mode.value = "authenticated"; authenticatedUserId.value = userId; sessionId.value = uuid(); resetEpoch.value += 1; touch(); }
  function setGuest(): void { mode.value = "guest"; authenticatedUserId.value = null; touch(); }
  function setBusy(value: boolean): void { busy.value = value; if (!value) touch(); }
  function reset(): void {
    mode.value = "guest";
    authenticatedUserId.value = null;
    sessionId.value = uuid();
    secondsRemaining.value = 120;
    resetEpoch.value += 1;
  }
  function start(): void {
    if (started) return;
    started = true;
    for (const event of ["pointerdown", "keydown", "touchstart"] as const) {
      window.addEventListener(event, touch, { passive: true });
    }
    timer = window.setInterval(() => {
      if (busy.value) return;
      secondsRemaining.value -= 1;
      if (secondsRemaining.value <= 0) {
        if (mode.value === "authenticated") { inactivityEpoch.value += 1; touch(); }
        else reset();
      }
    }, 1000);
  }
  function stop(): void {
    if (timer !== undefined) window.clearInterval(timer);
    timer = undefined;
    started = false;
  }

  return { mode, sessionId, userId, secondsRemaining, showCountdown, resetEpoch, inactivityEpoch, busy, touch, setMode, setAuthenticated, setGuest, setBusy, reset, start, stop };
});
