"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/badges";
import { QuestionCard } from "@/components/question-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  getInterview,
  markStep,
  myPlan,
  sendAnswer,
  submitInterview,
  type Answer,
  type InterviewState,
  type ParentPlan,
  type ParentStep,
} from "@/lib/api";
import { errorText, formatDate, PRIORITY_LABEL, STEP_STATUS_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

type Phase =
  | { kind: "loading" }
  | { kind: "interview"; state: InterviewState }
  | { kind: "generating" }
  | { kind: "review"; label: string }
  | { kind: "plan"; plan: ParentPlan }
  | { kind: "error"; message: string };

export default function ParentCasePage() {
  const { caseId } = useParams<{ caseId: string }>();
  return <AppShell role="parent">{() => <CaseFlow caseId={Number(caseId)} />}</AppShell>;
}

function CaseFlow({ caseId }: { caseId: number }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const buildPlan = useCallback(
    async (label: string) => {
      setPhase({ kind: "generating" });
      try {
        await submitInterview(caseId);
        setPhase({ kind: "review", label });
      } catch (err) {
        setPhase({ kind: "error", message: errorText(err, "Не удалось составить план") });
      }
    },
    [caseId],
  );

  // Server state → what to show. "needs-plan": the interview is over but the plan wasn't built (page closed).
  const apply = useCallback(
    (next: Phase | { kind: "needs-plan"; label: string }) =>
      next.kind === "needs-plan" ? buildPlan(next.label) : setPhase(next),
    [buildPlan],
  );

  useEffect(() => {
    let active = true;
    fetchPhase(caseId).then((next) => {
      if (active) apply(next);
    });
    return () => {
      active = false;
    };
  }, [caseId, apply]);

  async function reload() {
    setPhase({ kind: "loading" });
    await apply(await fetchPhase(caseId));
  }

  async function answer(a: Answer) {
    setAnswerError(null);
    setSending(true);
    try {
      const state = await sendAnswer(caseId, a);
      if (state.done) await buildPlan(state.case.label);
      else setPhase({ kind: "interview", state });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) await reload(); // question changed meanwhile
      else setAnswerError(errorText(err, "Не удалось отправить ответ"));
    } finally {
      setSending(false);
    }
  }

  switch (phase.kind) {
    case "loading":
      return <p className="text-sm text-muted-foreground">Загрузка…</p>;
    case "error":
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-destructive">{phase.message}</p>
          <Button variant="outline" onClick={reload}>
            Попробовать ещё раз
          </Button>
        </div>
      );
    case "interview":
      return (
        <div className="flex flex-col gap-4">
          <BackLink />
          <h1 className="text-xl font-semibold">{phase.state.case.label}</h1>
          <QuestionCard
            key={phase.state.question!.slot}
            question={phase.state.question!}
            answered={phase.state.answered}
            max={phase.state.max_questions}
            sending={sending}
            error={answerError}
            onAnswer={answer}
          />
        </div>
      );
    case "generating":
      return (
        <Card>
          <CardHeader>
            <CardTitle>Составляем план…</CardTitle>
            <CardDescription>
              Подбираем шаги, сроки и документы по вашим ответам. Это займёт до минуты.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
            </div>
          </CardContent>
        </Card>
      );
    case "review":
      return (
        <div className="flex flex-col gap-4">
          <BackLink />
          <Card>
            <CardHeader>
              <CardTitle>План на проверке у куратора</CardTitle>
              <CardDescription>
                Спасибо, ответы сохранены. Куратор проверит план для «{phase.label}» — после этого он
                появится здесь.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={reload}>
                Проверить ещё раз
              </Button>
            </CardContent>
          </Card>
        </div>
      );
    case "plan":
      return <PlanView plan={phase.plan} />;
  }
}

async function fetchPhase(caseId: number): Promise<Phase | { kind: "needs-plan"; label: string }> {
  try {
    const state = await getInterview(caseId);
    if (state.case.status === "approved") return { kind: "plan", plan: await myPlan(caseId) };
    if (state.case.status === "draft") return { kind: "review", label: state.case.label };
    if (state.question) return { kind: "interview", state };
    return { kind: "needs-plan", label: state.case.label };
  } catch (err) {
    return { kind: "error", message: errorText(err) };
  }
}

function BackLink() {
  return (
    <Link href="/parent" className="text-sm text-muted-foreground hover:text-foreground">
      ← Мои обращения
    </Link>
  );
}

function PlanView({ plan: initial }: { plan: ParentPlan }) {
  const [plan, setPlan] = useState(initial);
  const [busyStep, setBusyStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const titles = Object.fromEntries(plan.steps.map((s) => [s.step_id, s.title]));
  const { steps_done, steps_total } = plan.overdue;

  async function mark(stepId: string, done: boolean) {
    setError(null);
    setBusyStep(stepId);
    try {
      setPlan(await markStep(plan.case.id, stepId, done));
    } catch (err) {
      setError(errorText(err, "Не удалось сохранить"));
    } finally {
      setBusyStep(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <BackLink />
      <div>
        <h1 className="text-xl font-semibold">План для «{plan.case.label}»</h1>
        <p className="text-sm text-muted-foreground">
          Выполнено {steps_done} из {steps_total}. Сроки — нормативные, а не гарантия.
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <ol className="flex flex-col gap-3">
        {plan.steps.map((step, i) => (
          <StepCard
            key={step.step_id}
            step={step}
            index={i + 1}
            titles={titles}
            busy={busyStep === step.step_id}
            onMark={(done) => mark(step.step_id, done)}
          />
        ))}
      </ol>
    </div>
  );
}

function StepCard({
  step,
  index,
  titles,
  busy,
  onMark,
}: {
  step: ParentStep;
  index: number;
  titles: Record<string, string>;
  busy: boolean;
  onMark: (done: boolean) => void;
}) {
  const done = step.status === "done";
  return (
    <li>
      <Card className={cn(done && "bg-muted/40")}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Шаг {index}</span>
            <Badge className="border-border">{STEP_STATUS_LABEL[step.status]}</Badge>
            {step.priority === 1 && !done && (
              <Badge className="border-border bg-muted">{PRIORITY_LABEL[1]}</Badge>
            )}
          </div>
          <CardTitle className="text-base">{step.title}</CardTitle>
          <CardDescription>{step.parent_explanation}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
            <dt className="text-muted-foreground">Срок</dt>
            <dd>
              до {formatDate(step.due_date)}
              <span className="block text-xs text-muted-foreground">{step.deadline_note}</span>
              {step.days_overdue > 0 && (
                // Shown neutrally: the parent is not blamed, the curator follows up.
                <span className="block text-xs text-muted-foreground">
                  Срок прошёл {step.days_overdue} дн. назад — куратор видит это и поможет.
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">Куда обращаться</dt>
            <dd>
              {step.responsible}
              {step.channel.length > 0 && (
                <span className="block text-xs text-muted-foreground">{step.channel.join(" · ")}</span>
              )}
            </dd>
          </dl>

          {step.documents.length > 0 && (
            <div>
              <p className="mb-1 text-muted-foreground">Документы</p>
              <ul className="flex flex-col gap-1">
                {step.documents.map((d) => (
                  <li key={d.doc_code} className="flex gap-2">
                    <span aria-hidden className={d.on_hand ? "text-emerald-600" : "text-muted-foreground"}>
                      {d.on_hand ? "✓" : "○"}
                    </span>
                    <span>
                      {d.title}
                      {d.on_hand && <span className="text-xs text-muted-foreground"> — уже есть</span>}
                      {!d.on_hand && d.from_step && (
                        <span className="text-xs text-muted-foreground">
                          {" "}
                          — получите на шаге «{titles[d.from_step] ?? d.from_step}»
                        </span>
                      )}
                      {!d.on_hand && !d.from_step && d.auto_fetch && (
                        <span className="text-xs text-muted-foreground"> — подтянется автоматически</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {step.warning && <p className="rounded-lg bg-muted p-2 text-xs">{step.warning}</p>}

          <p className="text-xs text-muted-foreground">
            Основание:{" "}
            {step.legal_url ? (
              <a href={step.legal_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                {step.legal_source}
              </a>
            ) : (
              step.legal_source
            )}
          </p>

          <div className="flex flex-wrap items-center gap-3 border-t pt-3">
            {!done && (
              <Button variant="outline" disabled={busy} onClick={() => onMark(true)}>
                {busy ? "Сохраняем…" : "Отметить выполненным"}
              </Button>
            )}
            {done && step.completed_by === "parent" && (
              <>
                <span className="text-emerald-700">
                  ✓ Вы отметили выполненным{step.completed_at ? ` ${formatDate(step.completed_at)}` : ""}
                </span>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => onMark(false)}>
                  Отменить
                </Button>
              </>
            )}
            {done && step.completed_by !== "parent" && (
              <span className="text-emerald-700">✓ Куратор отметил шаг выполненным</span>
            )}
          </div>
        </CardContent>
      </Card>
    </li>
  );
}
