"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { logout, type User } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useRequireAuth } from "@/lib/use-auth";

const ROLES = [
  { href: "/parent", label: "Я родитель" },
  { href: "/curator", label: "Я куратор" },
];

/** Page frame for signed-in pages: header with the role switch, then the page once the user is known. */
export function AppShell({
  children,
  wide = false,
}: {
  children: (user: User) => React.ReactNode;
  wide?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, error } = useRequireAuth();

  return (
    <div className="flex flex-col">
      <header className="border-b bg-background">
        <div className={cn("mx-auto flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3", wide ? "max-w-6xl" : "max-w-3xl")}>
          <Link href="/" className="font-semibold">
            AqylRoute AI
          </Link>
          <nav className="flex gap-1">
            {ROLES.map((r) => (
              <Link
                key={r.href}
                href={r.href}
                className={cn(
                  "rounded-md px-2.5 py-1 text-sm",
                  pathname.startsWith(r.href) ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {r.label}
              </Link>
            ))}
          </nav>
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
        {!error && !user && <p className="text-sm text-muted-foreground">Загрузка…</p>}
        {user && children(user)}
      </div>
    </div>
  );
}
