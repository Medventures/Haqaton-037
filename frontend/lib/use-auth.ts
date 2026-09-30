"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getMe, getToken, logout, type User } from "@/lib/api";

/** The logged-in user, or null while loading. Sends the visitor to /login without a valid token. */
export function useRequireAuth(): { user: User | null; error: string | null } {
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

  return { user, error };
}
