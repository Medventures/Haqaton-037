"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CaseStatusBadge } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createCase, myCases, type Case } from "@/lib/api";
import { errorText, formatDate } from "@/lib/format";

export default function ParentPage() {
  return <AppShell role="parent">{() => <MyCases />}</AppShell>;
}

function MyCases() {
  const router = useRouter();
  const [cases, setCases] = useState<Case[] | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    myCases()
      .then(setCases)
      .catch((err) => setError(errorText(err)));
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStarting(true);
    try {
      const state = await createCase(label.trim() || "Мой ребёнок");
      router.push(`/parent/${state.case.id}`);
    } catch (err) {
      setError(errorText(err, "Не удалось начать интервью"));
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Мои обращения</h1>
        <p className="text-sm text-muted-foreground">
          Ответьте на несколько вопросов — мы составим пошаговый план, а куратор его проверит.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Новое обращение</CardTitle>
          <CardDescription>8–12 вопросов, около 5 минут. На любой вопрос можно ответить «Не знаю».</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={start} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="grid flex-1 gap-2">
              <Label htmlFor="label">Как обращаться к ребёнку</Label>
              <Input
                id="label"
                placeholder="Например: Алихан"
                maxLength={100}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <Button type="submit" size="lg" disabled={starting}>
              {starting ? "Начинаем…" : "Начать интервью"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {cases === null && !error && <p className="text-sm text-muted-foreground">Загрузка…</p>}
      {cases?.length === 0 && <p className="text-sm text-muted-foreground">Обращений пока нет.</p>}
      {cases && cases.length > 0 && (
        <ul className="flex flex-col gap-2">
          {cases.map((c) => (
            <li key={c.id}>
              <Link
                href={`/parent/${c.id}`}
                className="flex items-center justify-between gap-3 rounded-xl border p-4 hover:bg-muted/50"
              >
                <div>
                  <p className="font-medium">{c.label}</p>
                  <p className="text-xs text-muted-foreground">от {formatDate(c.created_at)}</p>
                </div>
                <CaseStatusBadge status={c.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
