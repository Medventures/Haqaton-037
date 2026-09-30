import type { CaseStatus, OverdueLevel } from "@/lib/api";
import { CASE_STATUS_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Badge({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const tone = {
    interview: "border-border text-muted-foreground",
    draft: "border-sky-200 bg-sky-50 text-sky-800",
    approved: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[status];
  return <Badge className={tone}>{CASE_STATUS_LABEL[status]}</Badge>;
}

/** Curator view only: yellow for 1–7 days late, red for more. */
export function OverdueBadge({ level, count, days }: { level: OverdueLevel; count?: number; days?: number }) {
  if (level === 0) return null;
  const tone = level === 1 ? "border-amber-300 bg-amber-50 text-amber-800" : "border-red-300 bg-red-50 text-red-700";
  const text = days !== undefined ? `Просрочка ${days} дн.` : `Просрочено: ${count}`;
  return <Badge className={tone}>{text}</Badge>;
}
