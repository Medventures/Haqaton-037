"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/badges";
import { QuestionCard } from "@/components/question-card";
import { UrgentAdvice } from "@/components/urgent-advice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  downloadCalendar,
  getInterview,
  markStep,
  myPlan,
  sendAnswer,
  submitInterview,
  type Answer,
  type InterviewState,
  type ParentPlan,
  type ParentStep,
  type RedFlag,
} from "@/lib/api";
import { errorText, formatDate } from "@/lib/format";
import { pick, useLang, useT, type Lang, type T } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Phase =
  | { kind: "loading" }
  | { kind: "interview"; state: InterviewState }
  | { kind: "generating" }
  | { kind: "review"; label: string; urgent: RedFlag[] }
  | { kind: "plan"; plan: ParentPlan }
  | { kind: "error"; message: string };

type Next = Phase | { kind: "needs-plan"; label: string; urgent: RedFlag[] };

export default function ParentCasePage() {
  const { caseId } = useParams<{ caseId: string }>();
  return <AppShell role="parent">{() => <CaseFlow caseId={Number(caseId)} />}</AppShell>;
}

function CaseFlow({ caseId }: { caseId: number }) {
  const t = useT();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const buildPlan = useCallback(
    async (label: string, urgent: RedFlag[]) => {
      setPhase({ kind: "generating" });
      try {
        await submitInterview(caseId);
        setPhase({ kind: "review", label, urgent });
      } catch (err) {
        setPhase({ kind: "error", message: errorText(err, t("interview.planFailed")) });
      }
    },
    [caseId, t],
  );

  // Server state → what to show. "needs-plan": the interview is over but the plan wasn't built (page closed).
  const apply = useCallback(
    (next: Next) => (next.kind === "needs-plan" ? buildPlan(next.label, next.urgent) : setPhase(next)),
    [buildPlan],
  );

  useEffect(() => {
    let active = true;
    fetchPhase(caseId, t).then((next) => {
      if (active) apply(next);
    });
    return () => {
      active = false;
    };
  }, [caseId, apply, t]);

  async function reload() {
    setPhase({ kind: "loading" });
    await apply(await fetchPhase(caseId, t));
  }

  async function answer(a: Answer) {
    setAnswerError(null);
    setSending(true);
    try {
      const state = await sendAnswer(caseId, a);
      if (state.done) await buildPlan(state.case.label, state.urgent_reasons);
      else setPhase({ kind: "interview", state });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) await reload(); // question changed meanwhile
      else setAnswerError(errorText(err, t("interview.sendFailed")));
    } finally {
      setSending(false);
    }
  }

  switch (phase.kind) {
    case "loading":
      return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
    case "error":
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-destructive">{phase.message}</p>
          <Button variant="outline" onClick={reload}>
            {t("common.retry")}
          </Button>
        </div>
      );
    case "interview":
      return (
        <div className="flex flex-col gap-4">
          <BackLink />
          <h1 className="text-xl font-semibold">{phase.state.case.label}</h1>
          <UrgentAdvice reasons={phase.state.urgent_reasons} />
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
            <CardTitle>{t("interview.generating.title")}</CardTitle>
            <CardDescription>{t("interview.generating.text")}</CardDescription>
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
          <UrgentAdvice reasons={phase.urgent} />
          <Card>
            <CardHeader>
              <CardTitle>{t("review.title")}</CardTitle>
              <CardDescription>{t("review.text", { label: phase.label })}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={reload}>
                {t("review.check")}
              </Button>
            </CardContent>
          </Card>
        </div>
      );
    case "plan":
      return <PlanView plan={phase.plan} />;
  }
}

async function fetchPhase(caseId: number, t: T): Promise<Next> {
  try {
    const state = await getInterview(caseId);
    const urgent = state.urgent_reasons;
    if (state.case.status === "approved") return { kind: "plan", plan: await myPlan(caseId) };
    if (state.case.status === "draft") return { kind: "review", label: state.case.label, urgent };
    if (state.question) return { kind: "interview", state };
    return { kind: "needs-plan", label: state.case.label, urgent };
  } catch (err) {
    return { kind: "error", message: errorText(err, t("common.error")) };
  }
}

function BackLink() {
  const t = useT();
  return (
    <Link href="/parent" className="text-sm text-muted-foreground hover:text-foreground print:hidden">
      {t("parent.back")}
    </Link>
  );
}

function PlanView({ plan: initial }: { plan: ParentPlan }) {
  const t = useT();
  const [lang] = useLang();
  const [plan, setPlan] = useState(initial);
  const [busyStep, setBusyStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const titles = Object.fromEntries(plan.steps.map((s) => [s.step_id, pick(lang, s.title, s.title_kk)]));
  const { steps_done, steps_total } = plan.overdue;
  const next = plan.steps.find((s) => s.status !== "done");
  const percent = steps_total ? Math.round((steps_done / steps_total) * 100) : 0;

  async function mark(stepId: string, done: boolean) {
    setError(null);
    setBusyStep(stepId);
    try {
      setPlan(await markStep(plan.case.id, stepId, done));
    } catch (err) {
      setError(errorText(err, t("plan.saveFailed")));
    } finally {
      setBusyStep(null);
    }
  }

  async function calendar() {
    setError(null);
    try {
      await downloadCalendar(plan.case.id, lang);
    } catch (err) {
      setError(errorText(err, t("plan.calendarFailed")));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <BackLink />
      <div className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">{t("plan.title", { label: plan.case.label })}</h1>
        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={percent}>
            <div className="h-full rounded-full bg-emerald-600 transition-all" style={{ width: `${percent}%` }} />
          </div>
          <span className="text-sm text-muted-foreground tabular-nums">
            {t("plan.progress", { done: steps_done, total: steps_total })}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">{t("plan.legalNote")}</p>
        <div className="flex flex-wrap gap-2 print:hidden">
          <Button variant="outline" size="sm" onClick={calendar}>
            {t("plan.calendar")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => window.print()}>
            {t("plan.print")}
          </Button>
        </div>
      </div>

      <UrgentAdvice reasons={plan.urgent_reasons} />
      {error && <p className="text-sm text-destructive">{error}</p>}

      <NowCard
        step={next}
        busy={next ? busyStep === next.step_id : false}
        onDone={() => next && mark(next.step_id, true)}
      />

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

      <DocumentPassport steps={plan.steps} lang={lang} t={t} />
    </div>
  );
}

function NowCard({ step, busy, onDone }: { step: ParentStep | undefined; busy: boolean; onDone: () => void }) {
  const t = useT();
  const [lang] = useLang();
  return (
    <Card className="border-emerald-300 bg-emerald-50/60 ring-emerald-200">
      <CardHeader>
        <CardDescription className="font-medium text-emerald-800">{t("plan.now.title")}</CardDescription>
        {step ? (
          <>
            <CardTitle className="text-lg">{pick(lang, step.title, step.title_kk)}</CardTitle>
            <p className="text-sm">
              {t("plan.now.until", { date: formatDate(step.due_date) })} ·{" "}
              {pick(lang, step.responsible, step.responsible_kk)}
            </p>
          </>
        ) : (
          <CardTitle className="text-base">{t("plan.now.allDone")}</CardTitle>
        )}
      </CardHeader>
      {step && (
        <CardContent className="print:hidden">
          <Button disabled={busy} onClick={onDone}>
            {busy ? t("plan.saving") : t("plan.markDone")}
          </Button>
        </CardContent>
      )}
    </Card>
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
  const t = useT();
  const [lang] = useLang();
  const done = step.status === "done";
  return (
    <li className="break-inside-avoid">
      <Card className={cn(done && "bg-muted/40")}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">{t("plan.step", { n: index })}</span>
            <Badge className="border-border">{t(`status.${step.status}`)}</Badge>
            {step.priority === 1 && !done && <Badge className="border-border bg-muted">{t("priority.1")}</Badge>}
          </div>
          <CardTitle className="text-base">{pick(lang, step.title, step.title_kk)}</CardTitle>
          <CardDescription>{pick(lang, step.parent_explanation, step.parent_explanation_kk)}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
            <dt className="text-muted-foreground">{t("plan.deadline")}</dt>
            <dd>
              {t("plan.untilDate", { date: formatDate(step.due_date) })}
              {step.legal_url && (
                <a
                  href={step.legal_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-2 text-xs text-emerald-700 underline underline-offset-2 print:hidden"
                >
                  {t("plan.lawLink")}
                </a>
              )}
              <span className="block text-xs text-muted-foreground">
                {pick(lang, step.deadline_note, step.deadline_note_kk)}
              </span>
              {step.days_overdue > 0 && (
                // Shown neutrally: the parent is not blamed, the curator follows up.
                <span className="block text-xs text-muted-foreground">
                  {t("plan.lateNeutral", { n: step.days_overdue })}
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">{t("plan.where")}</dt>
            <dd>
              {pick(lang, step.responsible, step.responsible_kk)}
              {step.channel.length > 0 && (
                <span className="block text-xs text-muted-foreground">{step.channel.join(" · ")}</span>
              )}
            </dd>
          </dl>

          {step.documents.length > 0 && (
            <div>
              <p className="mb-1 text-muted-foreground">{t("plan.documents")}</p>
              <ul className="flex flex-col gap-1">
                {step.documents.map((d) => (
                  <li key={d.doc_code} className="flex gap-2">
                    <span aria-hidden className={d.on_hand ? "text-emerald-600" : "text-muted-foreground"}>
                      {d.on_hand ? "✓" : "○"}
                    </span>
                    <span>
                      {pick(lang, d.title, d.title_kk)}
                      {d.on_hand && <span className="text-xs text-muted-foreground"> — {t("plan.doc.have")}</span>}
                      {!d.on_hand && d.from_step && (
                        <span className="text-xs text-muted-foreground">
                          {" "}
                          — {t("plan.doc.fromStep", { step: titles[d.from_step] ?? d.from_step })}
                        </span>
                      )}
                      {!d.on_hand && !d.from_step && d.auto_fetch && (
                        <span className="text-xs text-muted-foreground"> — {t("plan.doc.auto")}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {step.warning && <p className="rounded-lg bg-muted p-2 text-xs">{step.warning}</p>}

          <p className="text-xs text-muted-foreground">
            {t("plan.basis")}{" "}
            {step.legal_url ? (
              <a href={step.legal_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                {step.legal_source}
              </a>
            ) : (
              step.legal_source
            )}
          </p>

          <div className="flex flex-wrap items-center gap-3 border-t pt-3 print:hidden">
            {!done && (
              <Button variant="outline" disabled={busy} onClick={() => onMark(true)}>
                {busy ? t("plan.saving") : t("plan.markDone")}
              </Button>
            )}
            {done && step.completed_by === "parent" && (
              <>
                <span className="text-emerald-700">
                  {t("plan.doneByYou", { date: step.completed_at ? formatDate(step.completed_at) : "" })}
                </span>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => onMark(false)}>
                  {t("plan.undo")}
                </Button>
              </>
            )}
            {done && step.completed_by !== "parent" && (
              <span className="text-emerald-700">{t("plan.doneByCurator")}</span>
            )}
          </div>
        </CardContent>
      </Card>
    </li>
  );
}

type PassportState = "need" | "willGet" | "auto" | "have";

/** Every document of the plan once: whether the family has it, gets it on a step, or must prepare it. */
function DocumentPassport({ steps, lang, t }: { steps: ParentStep[]; lang: Lang; t: T }) {
  const docs = new Map<string, { title: string; state: PassportState; from: string | null; usedIn: number[] }>();
  const titleOf = (id: string) => {
    const s = steps.find((x) => x.step_id === id);
    return s ? pick(lang, s.title, s.title_kk) : id;
  };
  steps.forEach((step, i) => {
    for (const d of step.documents) {
      const state: PassportState = d.on_hand ? "have" : d.from_step ? "willGet" : d.auto_fetch ? "auto" : "need";
      const entry = docs.get(d.doc_code) ?? {
        title: pick(lang, d.title, d.title_kk),
        state,
        from: d.from_step,
        usedIn: [],
      };
      entry.usedIn.push(i + 1);
      docs.set(d.doc_code, entry);
    }
  });
  if (docs.size === 0) return null;

  const order: PassportState[] = ["need", "willGet", "auto", "have"];
  const tone: Record<PassportState, string> = {
    need: "border-amber-300 bg-amber-50 text-amber-800",
    willGet: "border-sky-200 bg-sky-50 text-sky-800",
    auto: "border-border text-muted-foreground",
    have: "border-emerald-200 bg-emerald-50 text-emerald-800",
  };
  const label: Record<PassportState, string> = {
    need: t("plan.passport.need"),
    willGet: t("plan.passport.willGet"),
    auto: t("plan.passport.auto"),
    have: t("plan.passport.have"),
  };
  const entries = [...docs.values()].sort((a, b) => order.indexOf(a.state) - order.indexOf(b.state));

  return (
    <Card className="break-inside-avoid">
      <CardHeader>
        <CardTitle>{t("plan.passport.title")}</CardTitle>
        <CardDescription>{t("plan.passport.text")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {entries.map((d) => (
            <li key={d.title} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <Badge className={tone[d.state]}>{label[d.state]}</Badge>
              <span className="font-medium">{d.title}</span>
              <span className="text-xs text-muted-foreground">
                {t("plan.passport.usedIn", { steps: d.usedIn.join(", ") })}
                {d.state === "willGet" && d.from ? ` · ${t("plan.passport.givenBy", { step: titleOf(d.from) })}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
