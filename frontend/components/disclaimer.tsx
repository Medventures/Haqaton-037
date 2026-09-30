"use client";

import { useT } from "@/lib/i18n";

export function Disclaimer() {
  const t = useT();
  return (
    <footer className="border-t px-4 py-3 text-center text-xs text-muted-foreground print:hidden">
      {t("disclaimer")}
    </footer>
  );
}
