"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { AuthCard } from "@/components/auth-card";
import { Button, buttonVariants } from "@/components/ui/button";
import { logout } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";

export default function HomePage() {
  const router = useRouter();
  const { user, error } = useRequireAuth();

  if (error) return <p className="p-8 text-center text-sm text-destructive">{error}</p>;
  if (!user) return <p className="p-8 text-center text-sm text-muted-foreground">Загрузка…</p>;

  return (
    <AuthCard title={`Здравствуйте, ${user.first_name}!`} description="Кем вы заходите сегодня?">
      <div className="flex flex-col gap-3">
        <Link href="/parent" className={buttonVariants({ size: "lg" })}>
          Я родитель
        </Link>
        <Link href="/curator" className={buttonVariants({ size: "lg", variant: "outline" })}>
          Я куратор
        </Link>
        <p className="text-xs text-muted-foreground">
          В демо куратором может войти любой пользователь.
        </p>
        <Button
          variant="ghost"
          onClick={() => {
            logout();
            router.replace("/login");
          }}
        >
          Выйти
        </Button>
      </div>
    </AuthCard>
  );
}
