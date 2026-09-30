"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { HOME } from "@/components/app-shell";
import { buttonVariants } from "@/components/ui/button";
import { Button } from "@/components/ui/button";
import { ApiError, getMe, getToken, login, logout } from "@/lib/api";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "@/lib/demo";
import type { Key } from "@/lib/dictionary";
import { LanguageSwitch, useT } from "@/lib/i18n";

const noSubscribe = () => () => {};

/** Signed-in users go to their section; everyone else sees the landing page with demo logins. */
export default function HomePage() {
  const router = useRouter();
  const hasToken = useSyncExternalStore(noSubscribe, () => Boolean(getToken()), () => false);
  const [anonymous, setAnonymous] = useState(false);

  useEffect(() => {
    if (!hasToken) return;
    getMe()
      .then((user) => router.replace(HOME[user.role]))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) logout();
        setAnonymous(true);
      });
  }, [hasToken, router]);

  if (hasToken && !anonymous) return null;
  return <Landing />;
}

function Landing() {
  const t = useT();
  const router = useRouter();
  const [busy, setBusy] = useState<"parent" | "curator" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function demo(role: "parent" | "curator") {
    setError(null);
    setBusy(role);
    try {
      const user = await login(DEMO_ACCOUNTS[role], DEMO_PASSWORD);
      router.replace(HOME[user.role]);
    } catch {
      setError(t("landing.demo.failed"));
      setBusy(null);
    }
  }

  const how: Key[][] = [
    ["landing.how.1.title", "landing.how.1.text"],
    ["landing.how.2.title", "landing.how.2.text"],
    ["landing.how.3.title", "landing.how.3.text"],
  ];
  const why: Key[][] = [
    ["landing.why.1.title", "landing.why.1.text"],
    ["landing.why.2.title", "landing.why.2.text"],
    ["landing.why.3.title", "landing.why.3.text"],
    ["landing.why.4.title", "landing.why.4.text"],
  ];

  return (
    <div className="flex flex-col">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <span className="font-semibold">{t("brand.name")}</span>
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitch />
            <Link href="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              {t("landing.cta.login")}
            </Link>
          </div>
        </div>
      </header>

      <section className="border-b bg-gradient-to-b from-emerald-50 to-background">
        <div className="mx-auto grid max-w-5xl gap-8 px-4 py-12 md:grid-cols-[1.4fr_1fr] md:items-center md:py-16">
          <div className="flex flex-col gap-4">
            <p className="text-sm font-medium text-emerald-700">{t("brand.tagline")}</p>
            <h1 className="text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
              {t("landing.hero.title")}
            </h1>
            <p className="text-base text-muted-foreground">{t("landing.hero.text")}</p>
            <div className="flex flex-wrap gap-2">
              <Link href="/register" className={buttonVariants({ size: "lg" })}>
                {t("landing.cta.register")}
              </Link>
              <Link href="/login" className={buttonVariants({ size: "lg", variant: "outline" })}>
                {t("landing.cta.login")}
              </Link>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-xl border bg-background p-5 shadow-sm">
            <p className="font-semibold">{t("landing.demo.title")}</p>
            <p className="text-sm text-muted-foreground">{t("landing.demo.text")}</p>
            <Button size="lg" disabled={busy !== null} onClick={() => demo("parent")}>
              {busy === "parent" ? t("auth.login.submitting") : t("landing.demo.parent")}
            </Button>
            <Button size="lg" variant="outline" disabled={busy !== null} onClick={() => demo("curator")}>
              {busy === "curator" ? t("auth.login.submitting") : t("landing.demo.curator")}
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-5xl px-4 py-10">
        <h2 className="mb-4 text-xl font-semibold">{t("landing.how.title")}</h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {how.map(([title, text], i) => (
            <li key={title} className="rounded-xl border p-4">
              <span className="text-sm font-semibold text-emerald-700">{i + 1}</span>
              <p className="mt-1 font-medium">{t(title)}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t(text)}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t bg-muted/30">
        <div className="mx-auto w-full max-w-5xl px-4 py-10">
          <h2 className="mb-4 text-xl font-semibold">{t("landing.why.title")}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {why.map(([title, text]) => (
              <div key={title} className="rounded-xl border bg-background p-4">
                <p className="font-medium">{t(title)}</p>
                <p className="mt-1 text-sm text-muted-foreground">{t(text)}</p>
              </div>
            ))}
          </div>
          <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            {t("landing.safety")}
          </p>
        </div>
      </section>
    </div>
  );
}
