"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Answer, Question } from "@/lib/api";
import { cn } from "@/lib/utils";

/** One interview question: option buttons, «Не знаю», and a free-text answer. Remount per question (key). */
export function QuestionCard({
  question,
  answered,
  max,
  sending,
  error,
  onAnswer,
}: {
  question: Question;
  answered: number;
  max: number;
  sending: boolean;
  error: string | null;
  onAnswer: (answer: Answer) => void;
}) {
  const { slot, kind } = question;
  const [picked, setPicked] = useState<number[]>([]);
  const [years, setYears] = useState("");
  const [months, setMonths] = useState("");
  const [text, setText] = useState("");
  const [freeText, setFreeText] = useState(kind === "text");

  const progress = Math.min(100, Math.round((answered / max) * 100));

  function submitNumber(e: React.FormEvent) {
    e.preventDefault();
    const total = kind === "age" ? Number(years || 0) * 12 + Number(months || 0) : Number(months || 0);
    if (Number.isFinite(total)) onAnswer({ slot, value: total });
  }

  function submitText(e: React.FormEvent) {
    e.preventDefault();
    if (text.trim()) onAnswer({ slot, text: text.trim() });
  }

  return (
    <Card>
      <CardHeader>
        <div className="mb-2 flex items-center gap-3">
          <div
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={answered}
            aria-valuemin={0}
            aria-valuemax={max}
          >
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
          </div>
          <span className="text-xs text-muted-foreground">
            {answered} из {max}
          </span>
        </div>
        <CardTitle className="text-lg">{question.text}</CardTitle>
        {question.hint && <CardDescription>{question.hint}</CardDescription>}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {kind === "choice" && (
          <div className="flex flex-col gap-2">
            {question.options.map((option, i) => (
              <Button
                key={option}
                variant="outline"
                size="lg"
                className="h-auto justify-start py-2.5 text-left whitespace-normal"
                disabled={sending}
                onClick={() => onAnswer({ slot, option: i })}
              >
                {option}
              </Button>
            ))}
          </div>
        )}

        {kind === "multi" && (
          <div className="flex flex-col gap-2">
            {question.options.map((option, i) => {
              const on = picked.includes(i);
              return (
                <Button
                  key={option}
                  variant="outline"
                  size="lg"
                  aria-pressed={on}
                  className={cn(
                    "h-auto justify-start py-2.5 text-left whitespace-normal",
                    on && "border-primary bg-muted",
                  )}
                  disabled={sending}
                  onClick={() => setPicked(on ? picked.filter((x) => x !== i) : [...picked, i])}
                >
                  <span aria-hidden className="w-4">
                    {on ? "✓" : ""}
                  </span>
                  {option}
                </Button>
              );
            })}
            <Button
              size="lg"
              disabled={sending || picked.length === 0}
              onClick={() => onAnswer({ slot, options: picked })}
            >
              Далее
            </Button>
          </div>
        )}

        {(kind === "age" || kind === "months") && !freeText && (
          <form onSubmit={submitNumber} className="flex flex-wrap items-end gap-3">
            {kind === "age" && (
              <div className="grid gap-1.5">
                <Label htmlFor="years">Лет</Label>
                <Input
                  id="years"
                  type="number"
                  min={0}
                  max={18}
                  inputMode="numeric"
                  className="w-24"
                  value={years}
                  onChange={(e) => setYears(e.target.value)}
                />
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="months">Месяцев</Label>
              <Input
                id="months"
                type="number"
                min={0}
                max={kind === "age" ? 11 : 216}
                inputMode="numeric"
                className="w-24"
                value={months}
                onChange={(e) => setMonths(e.target.value)}
              />
            </div>
            <Button type="submit" size="lg" disabled={sending || (!years && !months)}>
              Далее
            </Button>
          </form>
        )}

        {freeText && (
          <form onSubmit={submitText} className="flex flex-col gap-2">
            <Label htmlFor="free-text">{kind === "text" ? "Ваш ответ" : "Ответьте своими словами"}</Label>
            <textarea
              id="free-text"
              rows={kind === "text" ? 1 : 3}
              maxLength={500}
              className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              value={text}
              onChange={(e) => setText(e.target.value)}
              autoFocus
            />
            <Button type="submit" size="lg" disabled={sending || !text.trim()}>
              Далее
            </Button>
          </form>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-wrap gap-2 border-t pt-3">
          <Button variant="secondary" disabled={sending} onClick={() => onAnswer({ slot, dont_know: true })}>
            {question.dont_know_label}
          </Button>
          {kind !== "text" && (
            <Button variant="ghost" disabled={sending} onClick={() => setFreeText(!freeText)}>
              {freeText ? "Выбрать из вариантов" : "Ответить своими словами"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
