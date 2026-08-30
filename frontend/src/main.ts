import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";
import "./styles.css";
import "./kiosk.css";
import "./kiosk-v2.css";

const pinia = createPinia();
router.beforeEach(async (to) => {
  if (!["recommend", "path"].includes(String(to.name))) return true;
  const auth = useAuthStore(pinia);
  await auth.restore();
  if (auth.requireLogin(to.name === "path" ? "生成阅读路径" : "智能推荐")) return true;
  // Keep the login explanation visible on a real page instead of leaving the
  // protected route with an empty main region.  The requested feature remains
  // in AuthStore and is rendered by LoginDialog on the home surface.
  return { name: "home" };
});
createApp(App).use(pinia).use(router).mount("#app");
