import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router";
import "./styles.css";
import "./kiosk.css";
import "./kiosk-v2.css";

createApp(App).use(createPinia()).use(router).mount("#app");
