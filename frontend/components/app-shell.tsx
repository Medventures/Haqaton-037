"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { logout, type Role, type User } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useRequireAuth } from "@/lib/use-auth";

export const HOME: Record<Role, string> = { parent: "/parent", curator: "/curator" };
const ROLE_LABEL: Record<Role, string> = { parent: "Кабинет родителя", curator: "Кабинет куратора" };

/**
 * Page frame for signed-in pages. Each page belongs to one role; a user with the other role is sent
 * to their own section (roles never switch).
 */
export function AppShell({
  role,
  children,
  wide = false,
}: {
  role: Role;
  children: (user: User) => React.ReactNode;
  wide?: boolean;
}) {
  const router = useRouter();
  const { user, error } = useRequireAuth();
  const allowed = user?.role === role;

  useEffect(() => {
    if (user && user.role !== role) router.replace(HOME[user.role]);
  }, [user, role, router]);

  return (
    <div className="flex flex-col">
      <header className="border-b bg-background">
        <div className={cn("mx-auto flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3", wide ? "max-w-6xl" : "max-w-3xl")}>
          <Link href={HOME[role]} className="font-semibold">
            AqylRoute AI
          </Link>
          <span className="text-sm text-muted-foreground">{ROLE_LABEL[role]}</span>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {user && <span className="text-muted-foreground">{user.first_name}</span>}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logout();
                router.replace("/login");
              }}
            >
              Выйти
            </Button>
          </div>
        </div>
      </header>
      <div className={cn("mx-auto w-full px-4 py-6", wide ? "max-w-6xl" : "max-w-3xl")}>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && !allowed && <p className="text-sm text-muted-foreground">Загрузка…</p>}
        {user && allowed && children(user)}
      </div>
    </div>
  );
}
