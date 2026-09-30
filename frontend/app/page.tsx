"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { HOME } from "@/components/app-shell";
import { useRequireAuth } from "@/lib/use-auth";

/** After login: parents go to their cases, curators to the curator dashboard. No role switch. */
export default function HomePage() {
  const router = useRouter();
  const { user, error } = useRequireAuth();

  useEffect(() => {
    if (user) router.replace(HOME[user.role]);
  }, [user, router]);

  if (error) return <p className="p-8 text-center text-sm text-destructive">{error}</p>;
  return <p className="p-8 text-center text-sm text-muted-foreground">Загрузка…</p>;
}
