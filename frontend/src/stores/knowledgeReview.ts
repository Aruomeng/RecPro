import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { knowledgeReviewClient } from "../api/knowledgeReviewClient";
import type { KnowledgeReview, KnowledgeReviewAction, KnowledgeReviewStatus } from "../domain/knowledgeReview";
import { useAuthStore } from "./auth";

export const useKnowledgeReviewStore = defineStore("knowledgeReview", () => {
  const auth = useAuthStore();
  const items = ref<KnowledgeReview[]>([]);
  const filter = ref<KnowledgeReviewStatus | "ALL">("PENDING");
  const selectedId = ref("");
  const loading = ref(false);
  const error = ref("");
  const canReview = computed(() => auth.permissions.includes("catalog.knowledge.review"));
  const selected = computed(() => items.value.find((item) => item.proposal_uuid === selectedId.value) ?? items.value[0] ?? null);

  async function load(): Promise<void> {
    if (!canReview.value || !auth.accessToken) return;
    loading.value = true;
    try {
      items.value = await knowledgeReviewClient.list(auth.accessToken, filter.value === "ALL" ? undefined : filter.value);
      selectedId.value = items.value.some((item) => item.proposal_uuid === selectedId.value) ? selectedId.value : items.value[0]?.proposal_uuid ?? "";
      error.value = "";
    } catch { error.value = "知识审核数据暂时无法读取。"; }
    finally { loading.value = false; }
  }

  async function act(action: KnowledgeReviewAction): Promise<void> {
    if (!selected.value || !auth.accessToken || !canReview.value) return;
    loading.value = true;
    try {
      const reason = ({ APPROVE: "LIBRARIAN_EVIDENCE_ACCEPTED", REJECT: "LIBRARIAN_EVIDENCE_REJECTED", REQUEST_EVIDENCE: "LIBRARIAN_MORE_EVIDENCE_REQUIRED" } as const)[action];
      const result = await knowledgeReviewClient.act(auth.accessToken, selected.value.proposal_uuid, action, reason, crypto.randomUUID());
      items.value = items.value.map((item) => item.proposal_uuid === result.review.proposal_uuid ? result.review : item);
      error.value = "";
    } catch { error.value = "审核动作未能追加，请检查权限或幂等状态。"; }
    finally { loading.value = false; }
  }

  return { items, filter, selectedId, selected, loading, error, canReview, load, act };
});
