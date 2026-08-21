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
  return auth.requireLogin(to.name === "path" ? "生成阅读路径" : "智能推荐") || false;
});
createApp(App).use(pinia).use(router).mount("#app");
