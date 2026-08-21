<script setup lang="ts">
import { computed, ref } from "vue";

import { identityClient } from "../api/identityClient";
import type { ConsentScope } from "../domain/identity";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const tab = ref<"login" | "activate" | "reset">("login");
const identifierType = ref<"READER_NUMBER" | "STUDENT_NUMBER">("READER_NUMBER");
const identifier = ref("");
const password = ref("");
const currentPassword = ref("");
const confirmation = ref("");
const oneTimeCode = ref("");
const busy = ref(false);
const notice = ref("");
const consentBusy = ref<ConsentScope | null>(null);

const mustChangePassword = computed(() => Boolean(auth.authenticated && auth.account?.must_change_password));
const title = computed(() => mustChangePassword.value ? "首次登录必须修改密码" : auth.onboardingOpen ? "选择个性化授权" : tab.value === "login" ? "登录智慧图书馆" : tab.value === "activate" ? "激活读者账号" : "使用重置码修改密码");
const consentOptions: Array<{ scope: ConsentScope; title: string; text: string }> = [
  { scope: "DECLARED_PROFILE", title: "声明画像", text: "保存专业、年级、研究方向和语言偏好。" },
  { scope: "PERSONALIZED_RECOMMENDATION", title: "个性化推荐", text: "允许画像 Agent 在推荐时读取你的长期偏好摘要。" },
  { scope: "BEHAVIOR_LEARNING", title: "行为学习", text: "允许收藏、评分、借阅等新行为形成长期学习事实。" },
  { scope: "RESEARCH_ANALYTICS", title: "研究分析", text: "允许脱敏决策事实用于本地论文研究分析。" },
];

function close(): void {
  if (busy.value || mustChangePassword.value) return;
  auth.dialogOpen = false; auth.onboardingOpen = false; auth.error = "";
}
async function submitMandatoryChange(): Promise<void> {
  notice.value = "";
  if (password.value !== confirmation.value) { notice.value = "两次输入的新密码不一致。"; return; }
  busy.value = true;
  try {
    await auth.changePassword(currentPassword.value, password.value);
    currentPassword.value = ""; password.value = ""; confirmation.value = "";
    notice.value = "密码已更新，请重新登录。";
  } catch { notice.value = "密码修改失败，请确认当前密码和新密码要求。"; }
  finally { busy.value = false; }
}
async function submit(): Promise<void> {
  busy.value = true; notice.value = ""; auth.error = "";
  try {
    if (tab.value === "login") {
      await auth.login(identifierType.value, identifier.value, password.value);
      password.value = "";
      return;
    }
    if (password.value !== confirmation.value) { notice.value = "两次输入的密码不一致。"; return; }
    if (tab.value === "activate") {
      await identityClient.activate(identifierType.value, identifier.value, oneTimeCode.value, password.value);
      notice.value = "账号已激活，请切换到登录并使用新密码。";
    } else {
      await identityClient.completeReset(identifierType.value, identifier.value, oneTimeCode.value, password.value);
      notice.value = "密码已更新，请使用新密码登录。";
    }
    tab.value = "login"; password.value = ""; confirmation.value = ""; oneTimeCode.value = "";
  } catch { if (!auth.error) notice.value = "操作未完成，请检查证号、一次性码和密码。"; }
  finally { busy.value = false; }
}
async function toggleConsent(scope: ConsentScope): Promise<void> {
  consentBusy.value = scope;
  try { await auth.setConsent(scope, !auth.consents?.[scope], "LOGIN_ONBOARDING"); }
  finally { consentBusy.value = null; }
}
</script>

<template>
  <Transition name="drawer">
    <div v-if="auth.dialogOpen || auth.onboardingOpen" class="auth-layer" role="presentation" @click.self="close">
      <section class="auth-dialog" role="dialog" aria-modal="true" :aria-label="title">
        <button v-if="!mustChangePassword" class="icon-button auth-close" type="button" aria-label="关闭" @click="close">×</button>
        <span class="eyebrow">LIBRAMAS IDENTITY</span>
        <h2>{{ title }}</h2>

        <template v-if="mustChangePassword">
          <p class="auth-intro">这是首次登录或馆员重置后的安全步骤。修改成功后，当前会话会失效，你需要使用新密码重新登录。</p>
          <form class="auth-form" @submit.prevent="submitMandatoryChange">
            <label><span>当前密码</span><input v-model="currentPassword" required minlength="10" maxlength="128" type="password" autocomplete="current-password" /></label>
            <label><span>新密码</span><input v-model="password" required minlength="10" maxlength="128" type="password" autocomplete="new-password" /></label>
            <label><span>再次输入新密码</span><input v-model="confirmation" required minlength="10" maxlength="128" type="password" autocomplete="new-password" /></label>
            <p v-if="notice" class="auth-message" role="status">{{ notice }}</p>
            <button class="primary-action auth-submit" type="submit" :disabled="busy">{{ busy ? '正在修改…' : '修改密码并退出当前会话' }}</button>
          </form>
        </template>

        <template v-else-if="auth.onboardingOpen && auth.authenticated">
          <p class="auth-intro">授权由你逐项决定，未授权不会影响馆藏与知识图谱浏览。你可以随时撤回，撤回不会删除既有审计事实，但会立即停止新的长期学习。</p>
          <div class="consent-list">
            <article v-for="option in consentOptions" :key="option.scope" class="consent-card">
              <div><h3>{{ option.title }}</h3><p>{{ option.text }}</p></div>
              <button type="button" :class="{ granted: auth.consents?.[option.scope] }" :disabled="consentBusy !== null" @click="toggleConsent(option.scope)">
                {{ auth.consents?.[option.scope] ? '已授权，点击撤回' : '保持关闭 / 点击授权' }}
              </button>
            </article>
          </div>
          <button class="primary-action auth-finish" type="button" @click="auth.onboardingOpen = false">完成并继续</button>
        </template>

        <template v-else>
          <p class="auth-intro"><template v-if="auth.requestedFeature">“{{ auth.requestedFeature }}”需要登录。</template> 登录后推荐、阅读路径和 Agent Workspace 才会绑定到你的真实账号。</p>
          <div class="auth-tabs" role="tablist">
            <button v-for="item in ([['login','登录'],['activate','激活账号'],['reset','忘记密码']] as const)" :key="item[0]" type="button" :class="{ active: tab === item[0] }" @click="tab = item[0]">{{ item[1] }}</button>
          </div>
          <form class="auth-form" @submit.prevent="submit">
            <label><span>登录标识类型</span><select v-model="identifierType"><option value="READER_NUMBER">读者证号</option><option value="STUDENT_NUMBER">学工号</option></select></label>
            <label><span>{{ identifierType === 'READER_NUMBER' ? '读者证号' : '学工号' }}</span><input v-model.trim="identifier" required minlength="3" maxlength="64" autocomplete="username" placeholder="请输入完整号码" /></label>
            <label v-if="tab !== 'login'"><span>{{ tab === 'activate' ? '激活码' : '馆员签发的重置码' }}</span><input v-model.trim="oneTimeCode" required minlength="16" maxlength="256" autocomplete="one-time-code" placeholder="一次性码仅使用一次" /></label>
            <label><span>{{ tab === 'login' ? '密码' : '新密码' }}</span><input v-model="password" required minlength="10" maxlength="128" type="password" :autocomplete="tab === 'login' ? 'current-password' : 'new-password'" placeholder="至少 10 个字符" /></label>
            <label v-if="tab !== 'login'"><span>再次输入新密码</span><input v-model="confirmation" required minlength="10" maxlength="128" type="password" autocomplete="new-password" /></label>
            <p v-if="auth.error || notice" class="auth-message" role="status">{{ auth.error || notice }}</p>
            <button class="primary-action auth-submit" type="submit" :disabled="busy">{{ busy ? '正在安全处理…' : tab === 'login' ? '登录' : tab === 'activate' ? '激活账号' : '完成密码重置' }}</button>
          </form>
          <p class="auth-security-note">账号由馆员创建；系统不会在浏览器本地存储 Access Token 或 Refresh Token 明文。</p>
        </template>
      </section>
    </div>
  </Transition>
</template>
