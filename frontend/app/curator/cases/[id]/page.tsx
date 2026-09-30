"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge, CaseStatusBadge, OverdueBadge, UrgentBadge } from "@/components/badges";
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
  removeStep,
  updateStep,
  type CaseDetail,
  type Escalation,
  type Plan,
  type PlanStep,
  type Service,
  type StepPatch,
  type StepStatus,
} from "@/lib/api";
import type { Key } from "@/lib/dictionary";
import { errorText, formatDate } from "@/lib/format";
import { pick, useLang, useT } from "@/lib/i18n";
import { useSimDate } from "@/lib/sim-date";
import { cn } from "@/lib/utils";

const MAX_RATIONALE = 400;
const MAX_EXPLANATION = 600;
const TEXTAREA =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";
const STATUSES: StepStatus[] = ["todo", "in_progress", "done", "blocked"];

export default function CuratorCasePage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell role="curator" wide>{() => <CaseView caseId={Number(id)} />}</AppShell>;
}

function CaseView({ caseId }: { caseId: number }) {
  const t = useT();
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
      .catch((err) => active && setError(errorText(err, t("common.error"))));
    return () => {
      active = false;
    };
  }, [caseId, today, t]);

  useEffect(() => {
    listServices()
      .then(setServices)
      .catch(() => setServices([]));
  }, []);

  /** Run a change, then reload the case (plan, events). Returns the error text, or null on success. */
  async function act(action: () => Promise<unknown>, fallback: Key): Promise<string | null> {
    setError(null);
    setBusy(true);
    try {
      await action();
      setDetail(await caseDetail(caseId, today!));
      return null;
    } catch (err) {
      const message = errorText(err, t(fallback));
      setError(message);
      return message;
    } finally {
      setBusy(false);
    }
  }

  if (!today || (!detail && !error)) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  if (!detail) return <p className="text-sm text-destructive">{error}</p>;

  const { case: c, plan } = detail;
  const urgent = plan?.plan.urgent_reasons ?? [];

  return (
    <div className="flex flex-col gap-5">
      <Link href="/curator" className="text-sm text-muted-foreground hover:text-foreground">
        {t("case.back")}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{c.label}</h1>
            <CaseStatusBadge status={c.status} />
            <UrgentBadge reasons={urgent} />
            {plan && <OverdueBadge level={plan.overdue.worst_level} count={plan.overdue.overdue_count} />}
          </div>
          <p className="text-sm text-muted-foreground">
            {t("case.parent", { name: detail.parent_name })} · {t("common.from", { date: formatDate(c.created_at) })}
          </p>
        </div>
        <SimDateControl value={today} onChange={setToday} />
      </div>

      {urgent.length > 0 && (
        <p role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {t("case.urgent", { reasons: urgent.map((r) => t(`red.${r}`)).join(", ") })}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {plan && c.status === "draft" && (
          <Button disabled={busy} onClick={() => act(() => approvePlan(plan.id, today), "case.approveFailed")}>
            {t("case.approve")}
          </Button>
        )}
        {plan ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => act(() => generatePlan(c.id, true), "case.regenerateFailed")}
          >
            {t("case.regenerate")}
          </Button>
        ) : (
          <Button disabled={busy} onClick={() => act(() => generatePlan(c.id), "case.generateFailed")}>
            {t("case.generate")}
          </Button>
        )}
      </div>
      {plan && c.status === "approved" && <p className="text-xs text-muted-foreground">{t("case.approvedNote")}</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!plan && (
        <p className="text-sm text-muted-foreground">
          {c.status === "interview" ? t("case.interviewing", { n: detail.answers.length }) : t("case.noPlan")}
        </p>
      )}

      {plan && (
        <>
          <p className="text-xs text-muted-foreground">
            {t("case.texts", {
              source:
                plan.plan.generator === "ai" ? t("case.textsAi", { model: plan.plan.model ?? "" }) : t("case.textsCatalog"),
              done: plan.overdue.steps_done,
              total: plan.overdue.steps_total,
            })}
          </p>
          <ol className="flex flex-col gap-3">
            {plan.plan.steps.map((step) => (
              <StepRow
                key={step.step_id}
                step={step}
                busy={busy}
                dependents={plan.plan.steps.filter((s) => s.depends_on.includes(step.service_id)).map((s) => s.title)}
                onPatch={(patch) => act(() => updateStep(plan.id, step.step_id, patch, today), "step.saveFailed")}
                onRemove={(reason) => act(() => removeStep(plan.id, step.step_id, reason, today), "step.removeFailed")}
                onEscalate={() =>
                  act(async () => setEscalation(await escalateStep(plan.id, step.step_id, today)), "step.escalateFailed")
                }
              />
            ))}
          </ol>
          <AddStep
            plan={plan}
            services={services}
            busy={busy}
            onAdd={(serviceId) => act(() => addStep(plan.id, serviceId, today), "add.failed")}
          />
          {plan.plan.removed.length > 0 && (
            <Card size="sm">
              <CardHeader>
                <CardTitle>{t("removed.title")}</CardTitle>
                <CardDescription>{t("removed.text")}</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-2 text-sm">
                  {plan.plan.removed.map((r) => (
                    <li key={`${r.service_id}-${r.removed_at}`}>
                      <p className="font-medium">{r.title}</p>
                      <p className="text-muted-foreground">
                        {formatDate(r.removed_at)} · {r.reason}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
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
  dependents,
  onPatch,
  onRemove,
  onEscalate,
}: {
  step: PlanStep;
  busy: boolean;
  dependents: string[];
  onPatch: (patch: StepPatch) => Promise<string | null>;
  onRemove: (reason: string) => Promise<string | null>;
  onEscalate: () => void;
}) {
  const t = useT();
  const [lang] = useLang();
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const title = pick(lang, step.title, step.title_kk);
  return (
    <li>
      <Card size="sm" className={cn(step.overdue_level === 2 && "ring-red-300", step.overdue_level === 1 && "ring-amber-300")}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="border-border">{t(`sector.${step.sector}` as Key)}</Badge>
            <OverdueBadge level={step.overdue_level} days={step.days_overdue} />
            {step.completed_by === "parent" && step.completed_at && (
              <Badge className="border-emerald-200 bg-emerald-50 text-emerald-800">
                {t("step.byParent", { date: formatDate(step.completed_at) })}
              </Badge>
            )}
            {step.text_source === "fallback" && (
              <span className="text-xs text-muted-foreground">{t("step.fromCatalog")}</span>
            )}
            {step.text_source === "curator" && (
              <span className="text-xs text-muted-foreground">{t("step.byCurator")}</span>
            )}
          </div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{pick(lang, step.responsible, step.responsible_kk)}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-xs text-muted-foreground">
              {t("step.status")}
              <select
                className={selectClass}
                value={step.status}
                disabled={busy}
                onChange={(e) => onPatch({ status: e.target.value as StepStatus })}
              >
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {t(`status.${value}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-muted-foreground">
              {t("step.priority")}
              <select
                className={selectClass}
                value={step.priority}
                disabled={busy}
                onChange={(e) => onPatch({ priority: Number(e.target.value) as 1 | 2 | 3 })}
              >
                {([1, 2, 3] as const).map((p) => (
                  <option key={p} value={p}>
                    {p} — {t(`priority.${p}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-muted-foreground">
              {t("step.deadline")}
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
                {t("step.escalate")}
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{pick(lang, step.deadline_note, step.deadline_note_kk)}</p>

          {editing ? (
            <TextEditor step={step} busy={busy} onSave={onPatch} onClose={() => setEditing(false)} />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium text-muted-foreground">{t("step.rationale")}</p>
                <p>{step.rationale}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">{t("step.parentText")}</p>
                <p>{pick(lang, step.parent_explanation, step.parent_explanation_kk)}</p>
              </div>
            </div>
          )}

          {step.documents.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t("step.documents", {
                list: step.documents
                  .map((d) => {
                    const name = pick(lang, d.title, d.title_kk);
                    if (d.on_hand) return `${name} (${t("step.docHave")})`;
                    return d.from_step ? `${name} (${t("step.docFrom", { step: d.from_step })})` : name;
                  })
                  .join("; "),
              })}
            </p>
          )}
          {step.warning && <p className="rounded-lg bg-muted p-2 text-xs">{step.warning}</p>}
          <p className="text-xs text-muted-foreground">{t("step.basis", { source: step.legal_source })}</p>

          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {!editing && (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => setEditing(true)}>
                {t("step.editTexts")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive"
              disabled={busy || dependents.length > 0}
              onClick={() => setRemoving(true)}
            >
              {t("step.remove")}
            </Button>
            {dependents.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {t("step.removeBlocked", { steps: dependents.map((d) => `«${d}»`).join(", ") })}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
      {removing && <RemoveDialog title={title} busy={busy} onRemove={onRemove} onClose={() => setRemoving(false)} />}
    </li>
  );
}

function TextEditor({
  step,
  busy,
  onSave,
  onClose,
}: {
  step: PlanStep;
  busy: boolean;
  onSave: (patch: StepPatch) => Promise<string | null>;
  onClose: () => void;
}) {
  const t = useT();
  const [rationale, setRationale] = useState(step.rationale);
  const [explanation, setExplanation] = useState(step.parent_explanation);
  const [explanationKk, setExplanationKk] = useState(step.parent_explanation_kk ?? "");
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const patch: StepPatch = {};
    if (rationale.trim() !== step.rationale) patch.rationale = rationale.trim();
    if (explanation.trim() !== step.parent_explanation) patch.parent_explanation = explanation.trim();
    if (explanationKk.trim() && explanationKk.trim() !== (step.parent_explanation_kk ?? ""))
      patch.parent_explanation_kk = explanationKk.trim();
    if (Object.keys(patch).length === 0) return onClose();
    const err = await onSave(patch);
    if (err) setError(err);
    else onClose();
  }

  const fields: { label: Key; value: string; set: (v: string) => void; max: number; note?: boolean }[] = [
    { label: "step.rationale", value: rationale, set: setRationale, max: MAX_RATIONALE },
    { label: "step.parentText", value: explanation, set: setExplanation, max: MAX_EXPLANATION, note: true },
    { label: "step.parentTextKk", value: explanationKk, set: setExplanationKk, max: MAX_EXPLANATION, note: true },
  ];

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-muted/40 p-3">
      <div className="grid gap-3 lg:grid-cols-3">
        {fields.map((f) => (
          <label key={f.label} className="grid gap-1 text-xs font-medium text-muted-foreground">
            {t(f.label)}
            <textarea rows={4} maxLength={f.max} className={TEXTAREA} value={f.value} onChange={(e) => f.set(e.target.value)} />
            <span className="font-normal">
              {f.value.length} / {f.max}
              {f.note && ` · ${t("step.noDiagnosis")}`}
            </span>
          </label>
        ))}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || !rationale.trim() || !explanation.trim()} onClick={save}>
          {t("common.save")}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}

function RemoveDialog({
  title,
  busy,
  onRemove,
  onClose,
}: {
  title: string;
  busy: boolean;
  onRemove: (reason: string) => Promise<string | null>;
  onClose: () => void;
}) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    const err = await onRemove(reason.trim());
    if (err) setError(err);
    else onClose();
  }

  return (
    <Modal title={t("remove.title")} onClose={onClose}>
      <div className="flex flex-col gap-3 text-sm">
        <p>{t("remove.text", { title })}</p>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          {t("remove.reason")}
          <textarea
            rows={3}
            maxLength={300}
            autoFocus
            className={TEXTAREA}
            placeholder={t("remove.placeholder")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        {error && <p className="text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="destructive" disabled={busy || reason.trim().length < 3} onClick={remove}>
            {t("step.remove")}
          </Button>
        </div>
      </div>
    </Modal>
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
  const t = useT();
  const inPlan = new Set(plan.plan.steps.map((s) => s.service_id));
  const available = services.filter((s) => !inPlan.has(s.service_id));
  const [choice, setChoice] = useState("");
  const selected = available.find((s) => s.service_id === choice);
  const undecided = new Set(plan.plan.undecided);

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{t("add.title")}</CardTitle>
        <CardDescription>
          {t("add.text")}
          {plan.plan.undecided.length > 0 && t("add.undecided")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <select className={cn(selectClass, "min-w-0 flex-1")} value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">{t("add.choose")}</option>
            {available.map((s) => (
              <option key={s.service_id} value={s.service_id}>
                {undecided.has(s.service_id) ? "? " : ""}
                {s.title}
                {s.mode === "trigger" ? t("add.trigger") : ""}
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
            {t("add.submit")}
          </Button>
        </div>
        {selected?.ui_note && <p className="text-xs text-muted-foreground">{selected.ui_note}</p>}
      </CardContent>
    </Card>
  );
}

function InterviewCard({ detail }: { detail: CaseDetail }) {
  const t = useT();
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{t("answers.title")}</CardTitle>
        <CardDescription>{t("answers.text")}</CardDescription>
      </CardHeader>
      <CardContent>
        {detail.answers.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("answers.empty")}</p>
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
          <summary className="cursor-pointer text-muted-foreground">{t("answers.facts")}</summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-muted p-2">{JSON.stringify(detail.facts, null, 2)}</pre>
        </details>
      </CardContent>
    </Card>
  );
}

function EventsCard({ detail }: { detail: CaseDetail }) {
  const t = useT();
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{t("events.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {detail.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("events.empty")}</p>
        ) : (
          <ol className="flex flex-col gap-1.5 text-sm">
            {[...detail.events].reverse().map((e) => {
              const key = `event.${e.kind}` as Key;
              return (
                <li key={e.id} className="flex flex-wrap gap-x-2">
                  <span className="text-muted-foreground tabular-nums">{formatDate(e.created_at)}</span>
                  <span>{key in EVENT_KEYS ? t(key) : e.kind}</span>
                  {e.step_id && <span className="text-muted-foreground">{e.step_id}</span>}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

const EVENT_KEYS: Record<string, true> = Object.fromEntries(
  [
    "plan_generated",
    "plan_regenerated",
    "plan_approved",
    "step_updated",
    "step_added",
    "step_removed",
    "escalated",
    "step_done_by_parent",
    "step_reopened_by_parent",
  ].map((k) => [`event.${k}`, true]),
);

function EscalationDialog({ escalation, onClose }: { escalation: Escalation; onClose: () => void }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <Modal title={t("escalation.title")} onClose={onClose}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">
          {t("escalation.meta", { recipient: escalation.recipient, n: escalation.days_overdue })}
        </p>
        {escalation.warning && (
          <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-800">{escalation.warning}</p>
        )}
        <textarea readOnly rows={10} className="w-full rounded-lg border bg-muted/40 p-2 text-sm" value={escalation.message} />
        <p className="text-xs text-muted-foreground">{t("escalation.note")}</p>
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
            {copied ? t("escalation.copied") : t("escalation.copy")}
          </Button>
          <Button onClick={onClose}>{t("escalation.done")}</Button>
        </div>
      </div>
    </Modal>
  );
}
