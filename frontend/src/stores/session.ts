import { computed, ref } from "vue";
import { defineStore } from "pinia";

const GUEST_USER_ID = Number(import.meta.env.VITE_KIOSK_GUEST_USER_ID ?? 9000001);
const DEMO_USER_ID = Number(import.meta.env.VITE_KIOSK_DEMO_USER_ID ?? 1001);

function uuid(): string {
  return globalThis.crypto?.randomUUID?.() ?? `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export const useSessionStore = defineStore("session", () => {
  const mode = ref<"guest" | "demo">("guest");
  const sessionId = ref(uuid());
  const secondsRemaining = ref(120);
  const resetEpoch = ref(0);
  const busy = ref(false);
  let timer: number | undefined;
  let started = false;

  const userId = computed(() => mode.value === "demo" ? DEMO_USER_ID : GUEST_USER_ID);
  const showCountdown = computed(() => !busy.value && secondsRemaining.value <= 15);

  function touch(): void { secondsRemaining.value = 120; }
  function setMode(value: "guest" | "demo"): void { mode.value = value; touch(); }
  function setBusy(value: boolean): void { busy.value = value; if (!value) touch(); }
  function reset(): void {
    mode.value = "guest";
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
      if (secondsRemaining.value <= 0) reset();
    }, 1000);
  }
  function stop(): void {
    if (timer !== undefined) window.clearInterval(timer);
    timer = undefined;
    started = false;
  }

  return { mode, sessionId, userId, secondsRemaining, showCountdown, resetEpoch, busy, touch, setMode, setBusy, reset, start, stop };
});
