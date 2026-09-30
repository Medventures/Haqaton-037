"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CaseStatusBadge, OverdueBadge, UrgentBadge } from "@/components/badges";
import { SimDateControl } from "@/components/curator-ui";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listCases, type CaseList, type CuratorLoad } from "@/lib/api";
import { errorText, formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSimDate } from "@/lib/sim-date";
import { cn } from "@/lib/utils";

export default function CuratorPage() {
  return <AppShell role="curator" wide>{() => <CaseTable />}</AppShell>;
}

function CaseTable() {
  const t = useT();
  const [today, setToday] = useSimDate();
  const [data, setData] = useState<CaseList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!today) return;
    listCases(today)
      .then(setData)
      .catch((err) => setError(errorText(err, "")));
  }, [today]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("curator.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("curator.subtitle")}</p>
        </div>
        {today && <SimDateControl value={today} onChange={setToday} />}
      </div>

      {data && <LoadCard load={data.load} />}
      {error && <p className="text-sm text-destructive">{error || t("common.error")}</p>}
      {!data && !error && <p className="text-sm text-muted-foreground">{t("common.loading")}</p>}

      {data && data.cases.length === 0 && <p className="text-sm text-muted-foreground">{t("curator.empty")}</p>}
      {data && data.cases.length > 0 && (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">{t("curator.col.case")}</th>
                <th className="px-3 py-2 font-medium">{t("curator.col.parent")}</th>
                <th className="px-3 py-2 font-medium">{t("curator.col.status")}</th>
                <th className="px-3 py-2 font-medium">{t("curator.col.steps")}</th>
                <th className="px-3 py-2 font-medium">{t("curator.col.overdue")}</th>
              </tr>
            </thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.id} className={cn("border-t hover:bg-muted/30", c.urgent_reasons.length > 0 && "bg-red-50/50")}>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link href={`/curator/cases/${c.id}`} className="font-medium underline-offset-4 hover:underline">
                        {c.label}
                      </Link>
                      <UrgentBadge reasons={c.urgent_reasons} />
                    </div>
                    <span className="block text-xs text-muted-foreground">
                      {t("common.from", { date: formatDate(c.created_at) })}
                    </span>
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
                      <span className="text-xs text-muted-foreground">{t("curator.none")}</span>
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
  const t = useT();
  const tone = {
    below: "text-muted-foreground",
    within: "text-emerald-700",
    above: "text-red-700",
  }[load.state];
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{t("curator.load.title")}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">
          {load.active_cases}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            {t("curator.load.value", { min: load.norm_min, max: load.norm_max })}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-xs">
        <span className={cn("font-medium", tone)}>{t(`curator.load.${load.state}`)}</span>
        <span className="text-muted-foreground"> · {load.norm_source}</span>
      </CardContent>
    </Card>
  );
}
