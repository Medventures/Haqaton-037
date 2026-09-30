"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge, CaseStatusBadge, OverdueBadge } from "@/components/badges";
import { Modal, selectClass, SimDateControl } from "@/components/curator-ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  addStep,
  approvePlan,
  caseDetail,
  escalateStep,
  generatePlan,
  listServices,
  updateStep,
  type CaseDetail,
  type Escalation,
  type Plan,
  type PlanStep,
  type Service,
  type StepPatch,
  type StepStatus,
} from "@/lib/api";
import { errorText, formatDate, PRIORITY_LABEL, SECTOR_LABEL, STEP_STATUS_LABEL } from "@/lib/format";
import { useSimDate } from "@/lib/sim-date";
import { cn } from "@/lib/utils";

const EVENT_LABEL: Record<string, string> = {
  plan_generated: "План составлен",
  plan_regenerated: "План пересоставлен",
  plan_approved: "План утверждён",
  step_updated: "Шаг изменён",
  step_added: "Шаг добавлен",
  escalated: "Эскалация",
  step_done_by_parent: "Родитель отметил шаг выполненным",
  step_reopened_by_parent: "Родитель снял отметку о выполнении",
};

export default function CuratorCasePage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell role="curator" wide>{() => <CaseView caseId={Number(id)} />}</AppShell>;
}

function CaseView({ caseId }: { caseId: number }) {
  const [today, setToday] = useSimDate();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [services, setServices] = useState<Service[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [escalation, setEscalation] = useState<Escalation | null>(null);

  useEffect(() => {
    if (!today) return;
    let active = true;
    caseDetail(caseId, today)
      .then((d) => active && setDetail(d))
      .catch((err) => active && setError(errorText(err)));
    return () => {
      active = false;
    };
  }, [caseId, today]);

  useEffect(() => {
    listServices()
      .then(setServices)
      .catch(() => setServices([]));
  }, []);

  /** Run a change, then reload the case (plan, events). */
  async function act(action: () => Promise<unknown>, fallback: string) {
    setError(null);
    setBusy(true);
    try {
      await action();
      setDetail(await caseDetail(caseId, today!));
    } catch (err) {
      setError(errorText(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  if (!today || (!detail && !error)) return <p className="text-sm text-muted-foreground">Загрузка…</p>;
  if (!detail) return <p className="text-sm text-destructive">{error}</p>;

  const { case: c, plan } = detail;

  return (
    <div className="flex flex-col gap-5">
      <Link href="/curator" className="text-sm text-muted-foreground hover:text-foreground">
        ← Все случаи
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{c.label}</h1>
            <CaseStatusBadge status={c.status} />
            {plan && <OverdueBadge level={plan.overdue.worst_level} count={plan.overdue.overdue_count} />}
          </div>
          <p className="text-sm text-muted-foreground">
            Родитель: {detail.parent_name} · от {formatDate(c.created_at)}
          </p>
        </div>
        <SimDateControl value={today} onChange={setToday} />
      </div>

      <div className="flex flex-wrap gap-2">
        {plan && c.status === "draft" && (
          <Button disabled={busy} onClick={() => act(() => approvePlan(plan.id, today), "Не удалось утвердить")}>
            Утвердить план
          </Button>
        )}
        {plan ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => act(() => generatePlan(c.id, true), "Не удалось пересоставить план")}
          >
            Пересоставить план
          </Button>
        ) : (
          <Button disabled={busy} onClick={() => act(() => generatePlan(c.id), "Не удалось составить план")}>
            Составить план
          </Button>
        )}
      </div>
      {plan && c.status === "approved" && (
        <p className="text-xs text-muted-foreground">
          План утверждён и виден родителю. Пересоставление вернёт его на проверку.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!plan && (
        <p className="text-sm text-muted-foreground">
          {c.status === "interview"
            ? `Интервью идёт: ${detail.answers.length} ответов. План можно составить после последнего вопроса.`
            : "Плана пока нет."}
        </p>
      )}

      {plan && (
        <>
          <p className="text-xs text-muted-foreground">
            Тексты: {plan.plan.generator === "ai" ? `ИИ (${plan.plan.model})` : "из каталога"} · выполнено{" "}
            {plan.overdue.steps_done} из {plan.overdue.steps_total}
          </p>
          <ol className="flex flex-col gap-3">
            {plan.plan.steps.map((step) => (
              <StepRow
                key={step.step_id}
                step={step}
                busy={busy}
                onPatch={(patch) => act(() => updateStep(plan.id, step.step_id, patch, today), "Не удалось сохранить")}
                onEscalate={() =>
                  act(
                    async () => setEscalation(await escalateStep(plan.id, step.step_id, today)),
                    "Не удалось подготовить эскалацию",
                  )
                }
              />
            ))}
          </ol>
          <AddStep
            plan={plan}
            services={services}
            busy={busy}
            onAdd={(serviceId) => act(() => addStep(plan.id, serviceId, today), "Не удалось добавить шаг")}
          />
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <InterviewCard detail={detail} />
        <EventsCard detail={detail} />
      </div>

      {escalation && <EscalationDialog escalation={escalation} onClose={() => setEscalation(null)} />}
    </div>
  );
}

function StepRow({
  step,
  busy,
  onPatch,
  onEscalate,
}: {
  step: PlanStep;
  busy: boolean;
  onPatch: (patch: StepPatch) => void;
  onEscalate: () => void;
}) {
  return (
    <li>
      <Card size="sm" className={cn(step.overdue_level === 2 && "ring-red-300", step.overdue_level === 1 && "ring-amber-300")}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="border-border">{SECTOR_LABEL[step.sector] ?? step.sector}</Badge>
            <OverdueBadge level={step.overdue_level} days={step.days_overdue} />
            {step.completed_by === "parent" && step.completed_at && (
              <Badge className="border-emerald-200 bg-emerald-50 text-emerald-800">
                Отмечено родителем {formatDate(step.completed_at)}
              </Badge>
            )}
            {step.text_source === "fallback" && (
              <span className="text-xs text-muted-foreground">текст из каталога</span>
            )}
          </div>
          <CardTitle>{step.title}</CardTitle>
          <CardDescription>{step.responsible}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-xs text-muted-foreground">
              Статус
              <select
                className={selectClass}
                value={step.status}
                disabled={busy}
                onChange={(e) => onPatch({ status: e.target.value as StepStatus })}
              >
                {Object.entries(STEP_STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-muted-foreground">
              Приоритет
              <select
                className={selectClass}
                value={step.priority}
                disabled={busy}
                onChange={(e) => onPatch({ priority: Number(e.target.value) as 1 | 2 | 3 })}
              >
                {[1, 2, 3].map((p) => (
                  <option key={p} value={p}>
                    {p} — {PRIORITY_LABEL[p]}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-muted-foreground">
              Срок
              <Input
                type="date"
                className="w-auto"
                defaultValue={step.due_date}
                key={step.due_date}
                disabled={busy}
                onBlur={(e) => e.target.value && e.target.value !== step.due_date && onPatch({ due_date: e.target.value })}
              />
            </label>
            {step.days_overdue > 0 && (
              <Button variant="destructive" disabled={busy} onClick={onEscalate}>
                Эскалировать
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{step.deadline_note}</p>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <p className="text-xs font-medium text-muted-foreground">Почему в плане (для куратора)</p>
              <p>{step.rationale}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Что увидит родитель</p>
              <p>{step.parent_explanation}</p>
            </div>
          </div>

          {step.documents.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Документы:{" "}
              {step.documents
                .map((d) => `${d.title}${d.on_hand ? " (есть)" : d.from_step ? ` (из шага ${d.from_step})` : ""}`)
                .join("; ")}
            </p>
          )}
          {step.warning && <p className="rounded-lg bg-muted p-2 text-xs">{step.warning}</p>}
          <p className="text-xs text-muted-foreground">Основание: {step.legal_source}</p>
        </CardContent>
      </Card>
    </li>
  );
}

function AddStep({
  plan,
  services,
  busy,
  onAdd,
}: {
  plan: Plan;
  services: Service[];
  busy: boolean;
  onAdd: (serviceId: string) => void;
}) {
  const inPlan = new Set(plan.plan.steps.map((s) => s.service_id));
  const available = services.filter((s) => !inPlan.has(s.service_id));
  const [choice, setChoice] = useState("");
  const selected = available.find((s) => s.service_id === choice);
  const undecided = new Set(plan.plan.undecided);

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Добавить шаг</CardTitle>
        <CardDescription>
          Только услуги из каталога. Недостающие предварительные шаги добавятся сами.
          {plan.plan.undecided.length > 0 && " Отмеченные «?» не решены: в интервью не хватило ответов."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <select
            className={cn(selectClass, "min-w-0 flex-1")}
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          >
            <option value="">Выберите услугу…</option>
            {available.map((s) => (
              <option key={s.service_id} value={s.service_id}>
                {undecided.has(s.service_id) ? "? " : ""}
                {s.title}
                {s.mode === "trigger" ? " — по решению куратора" : ""}
              </option>
            ))}
          </select>
          <Button
            disabled={busy || !choice}
            onClick={() => {
              onAdd(choice);
              setChoice("");
            }}
          >
            Добавить
          </Button>
        </div>
        {selected?.ui_note && <p className="text-xs text-muted-foreground">{selected.ui_note}</p>}
      </CardContent>
    </Card>
  );
}

function InterviewCard({ detail }: { detail: CaseDetail }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Ответы интервью</CardTitle>
        <CardDescription>Только для куратора. Родителю не показываются.</CardDescription>
      </CardHeader>
      <CardContent>
        {detail.answers.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ответов нет.</p>
        ) : (
          <ol className="flex flex-col gap-2 text-sm">
            {detail.answers.map((a, i) => (
              <li key={i}>
                <p className="text-muted-foreground">{a.question_text}</p>
                <p>{a.raw_answer}</p>
              </li>
            ))}
          </ol>
        )}
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-muted-foreground">Факты (как их видят правила)</summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-muted p-2">{JSON.stringify(detail.facts, null, 2)}</pre>
        </details>
      </CardContent>
    </Card>
  );
}

function EventsCard({ detail }: { detail: CaseDetail }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>История</CardTitle>
      </CardHeader>
      <CardContent>
        {detail.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">Событий нет.</p>
        ) : (
          <ol className="flex flex-col gap-1.5 text-sm">
            {[...detail.events].reverse().map((e) => (
              <li key={e.id} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground tabular-nums">{formatDate(e.created_at)}</span>
                <span>{EVENT_LABEL[e.kind] ?? e.kind}</span>
                {e.step_id && <span className="text-muted-foreground">{e.step_id}</span>}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function EscalationDialog({ escalation, onClose }: { escalation: Escalation; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal title="Обращение в организацию" onClose={onClose}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">
          Получатель: {escalation.recipient} · просрочка {escalation.days_overdue} дн. Эскалация записана в
          историю случая.
        </p>
        {escalation.warning && (
          <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-800">{escalation.warning}</p>
        )}
        <textarea
          readOnly
          rows={10}
          className="w-full rounded-lg border bg-muted/40 p-2 text-sm"
          value={escalation.message}
        />
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(escalation.message);
                setCopied(true);
              } catch {
                setCopied(false);
              }
            }}
          >
            {copied ? "Скопировано" : "Скопировать текст"}
          </Button>
          <Button onClick={onClose}>Готово</Button>
        </div>
      </div>
    </Modal>
  );
}
