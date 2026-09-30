"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CaseStatusBadge, OverdueBadge } from "@/components/badges";
import { SimDateControl } from "@/components/curator-ui";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listCases, type CaseList, type CuratorLoad } from "@/lib/api";
import { errorText, formatDate } from "@/lib/format";
import { useSimDate } from "@/lib/sim-date";
import { cn } from "@/lib/utils";

export default function CuratorPage() {
  return <AppShell role="curator" wide>{() => <CaseTable />}</AppShell>;
}

function CaseTable() {
  const [today, setToday] = useSimDate();
  const [data, setData] = useState<CaseList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!today) return;
    listCases(today)
      .then(setData)
      .catch((err) => setError(errorText(err)));
  }, [today]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Кабинет куратора</h1>
          <p className="text-sm text-muted-foreground">Случаи с просрочкой — сверху.</p>
        </div>
        {today && <SimDateControl value={today} onChange={setToday} />}
      </div>

      {data && <LoadCard load={data.load} />}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!data && !error && <p className="text-sm text-muted-foreground">Загрузка…</p>}

      {data && data.cases.length === 0 && <p className="text-sm text-muted-foreground">Случаев пока нет.</p>}
      {data && data.cases.length > 0 && (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Случай</th>
                <th className="px-3 py-2 font-medium">Родитель</th>
                <th className="px-3 py-2 font-medium">Статус</th>
                <th className="px-3 py-2 font-medium">Шаги</th>
                <th className="px-3 py-2 font-medium">Просрочка</th>
              </tr>
            </thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.id} className="border-t hover:bg-muted/30">
                  <td className="px-3 py-2.5">
                    <Link href={`/curator/cases/${c.id}`} className="font-medium underline-offset-4 hover:underline">
                      {c.label}
                    </Link>
                    <span className="block text-xs text-muted-foreground">от {formatDate(c.created_at)}</span>
                  </td>
                  <td className="px-3 py-2.5">{c.parent_name}</td>
                  <td className="px-3 py-2.5">
                    <CaseStatusBadge status={c.status} />
                  </td>
                  <td className="px-3 py-2.5 tabular-nums">
                    {c.steps_total ? `${c.steps_done} / ${c.steps_total}` : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    {c.worst_level > 0 ? (
                      <OverdueBadge level={c.worst_level} count={c.overdue_count} />
                    ) : (
                      <span className="text-xs text-muted-foreground">нет</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LoadCard({ load }: { load: CuratorLoad }) {
  const tone = {
    below: "text-muted-foreground",
    within: "text-emerald-700",
    above: "text-red-700",
  }[load.state];
  const stateText = { below: "ниже нормы", within: "в пределах нормы", above: "выше нормы" }[load.state];
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>Нагрузка куратора</CardDescription>
        <CardTitle className="text-2xl tabular-nums">
          {load.active_cases}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            активных при норме {load.norm_min}–{load.norm_max}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-xs">
        <span className={cn("font-medium", tone)}>{stateText}</span>
        <span className="text-muted-foreground"> · {load.norm_source}</span>
      </CardContent>
    </Card>
  );
}
