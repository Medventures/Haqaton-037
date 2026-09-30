"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { ApiError, getMe, getToken, logout, type User } from "@/lib/api";

// TODO: role switch (parent / curator) goes here after auth.
export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    getMe()
      .then(setUser)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          router.replace("/login");
        } else {
          setError(err instanceof ApiError ? err.message : "Ошибка загрузки");
        }
      });
  }, [router]);

  if (error) return <p className="p-8 text-center text-sm text-destructive">{error}</p>;
  if (!user) return <p className="p-8 text-center text-sm text-muted-foreground">Загрузка…</p>;

  const fullName = [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(" ");

  return (
    <AuthCard title={`Здравствуйте, ${user.first_name}!`} description="Вы вошли в AqylRoute AI">
      <div className="flex flex-col gap-4 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted-foreground">ФИО</dt>
          <dd>{fullName}</dd>
          <dt className="text-muted-foreground">Телефон</dt>
          <dd>+{user.phone}</dd>
        </dl>
        <Button
          variant="outline"
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
