import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: () => import("./views/HomeView.vue") },
    { path: "/recommend", name: "recommend", component: () => import("./views/RecommendView.vue") },
    { path: "/graph", name: "graph", component: () => import("./views/GraphView.vue") },
    { path: "/path", name: "path", component: () => import("./views/ReadingPathView.vue") },
    { path: "/insights", name: "insights", component: () => import("./views/InsightsView.vue") },
    { path: "/knowledge-reviews", name: "knowledge-reviews", component: () => import("./views/KnowledgeReviewView.vue") },
    { path: "/system", name: "system", component: () => import("./views/SystemView.vue") },
  ],
});
