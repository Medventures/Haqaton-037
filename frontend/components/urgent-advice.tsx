"use client";

import type { RedFlag } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** Shown to the parent as soon as a red flag is answered, before and after the plan. */
export function UrgentAdvice({ reasons }: { reasons: RedFlag[] }) {
  const t = useT();
  if (reasons.length === 0) return null;
  return (
    <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900">
      <p className="font-semibold">{t("urgent.title")}</p>
      <p className="mt-1">{t("urgent.intro")}</p>
      <ul className="mt-2 flex list-disc flex-col gap-1 pl-5">
        {reasons.map((r) => (
          <li key={r}>{t(`urgent.${r}`)}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-red-800">{t("urgent.note")}</p>
    </div>
  );
}
