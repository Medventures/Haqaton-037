"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useT } from "@/lib/i18n";
import { demoDate, realToday } from "@/lib/sim-date";
import { cn } from "@/lib/utils";

/** «Симулировать дату»: overdue is computed against this date (?today=). */
export function SimDateControl({ value, onChange }: { value: string; onChange: (date: string) => void }) {
  const t = useT();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/40 px-3 py-2 text-sm">
      <label htmlFor="sim-date" className="font-medium">
        {t("sim.label")}
      </label>
      <Input
        id="sim-date"
        type="date"
        className="w-auto"
        value={value}
        onChange={(e) => e.target.value && onChange(e.target.value)}
      />
      <Button variant="ghost" size="sm" onClick={() => onChange(demoDate())}>
        {t("sim.demo")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => onChange(realToday())}>
        {t("sim.today")}
      </Button>
    </div>
  );
}

export const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

export function Modal({
  title,
  onClose,
  children,
  className,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn("w-full max-w-lg rounded-xl bg-background p-5 shadow-lg", className)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="✕">
            ✕
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}
