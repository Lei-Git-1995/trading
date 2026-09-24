export type Role = "user" | "assistant";

export type AiConfig = {
  id: number;
  name: string;
  baseUrl: string;
  modelName: string;
};

export type PromptTemplate = {
  ID?: number;
  id?: number;
  name?: string;
  content?: string;
  type?: string;
};

export type SessionMessage = {
  role: Role;
  content: string;
  reasoning?: string;
  time?: string;
};

export type VipStatus = {
  ok: boolean;
  vipLevel: number;
  active: boolean;
  message?: string;
};

/** 与桌面端一致：当前 data 配置下是否为 VIP2+ 且赞助在有效期内 */
export async function getVipStatus(): Promise<VipStatus> {
  const res = await fetch("/api/vip-status");
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function getAiConfigs(): Promise<AiConfig[]> {
  const res = await fetch("/api/ai-configs");
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function getPrompts(): Promise<PromptTemplate[]> {
  const res = await fetch("/api/prompts?name=&type=");
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function getSession(): Promise<SessionMessage[]> {
  const res = await fetch("/api/session");
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function saveSession(messages: SessionMessage[]): Promise<void> {
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function shareText(text: string, title = "AI助手"): Promise<string> {
  const res = await fetch("/api/share", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error || "分享失败");
  return data?.message || "已分享";
}

