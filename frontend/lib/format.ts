import type { CaseStatus, StepStatus } from "@/lib/api";

export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export const SECTOR_LABEL: Record<string, string> = {
  education: "Образование",
  health: "Здравоохранение",
  social: "Соцзащита",
};

export const CASE_STATUS_LABEL: Record<CaseStatus, string> = {
  interview: "Интервью",
  draft: "На проверке",
  approved: "Утверждён",
};

export const STEP_STATUS_LABEL: Record<StepStatus, string> = {
  todo: "Не начат",
  in_progress: "В работе",
  done: "Выполнен",
  blocked: "Остановлен",
};

export const PRIORITY_LABEL: Record<number, string> = {
  1: "В первую очередь",
  2: "Важно",
  3: "Можно позже",
};

export function errorText(err: unknown, fallback = "Ошибка загрузки"): string {
  return err instanceof Error && err.message ? err.message : fallback;
}
