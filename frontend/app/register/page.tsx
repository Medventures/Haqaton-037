"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, register, sendRegisterCode } from "@/lib/api";
import type { Key } from "@/lib/dictionary";
import { useT } from "@/lib/i18n";

type Form = {
  last_name: string;
  first_name: string;
  middle_name: string;
  phone: string;
  password: string;
  password2: string;
};

const FIELDS: { key: keyof Form; label: Key; type?: string; autoComplete: string; required: boolean }[] = [
  { key: "last_name", label: "auth.register.lastName", autoComplete: "family-name", required: true },
  { key: "first_name", label: "auth.register.firstName", autoComplete: "given-name", required: true },
  { key: "middle_name", label: "auth.register.middleName", autoComplete: "additional-name", required: false },
  { key: "phone", label: "auth.phone", type: "tel", autoComplete: "tel", required: true },
  { key: "password", label: "auth.register.password", type: "password", autoComplete: "new-password", required: true },
  { key: "password2", label: "auth.register.password2", type: "password", autoComplete: "new-password", required: true },
];

export default function RegisterPage() {
  const router = useRouter();
  const t = useT();
  const [form, setForm] = useState<Form>({
    last_name: "",
    first_name: "",
    middle_name: "",
    phone: "",
    password: "",
    password2: "",
  });
  const [step, setStep] = useState<"form" | "code">("form");
  const [code, setCode] = useState("");
  const [resendIn, setResendIn] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  async function requestCode() {
    setError(null);
    setLoading(true);
    try {
      const res = await sendRegisterCode(form.phone);
      setResendIn(res.resend_in);
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("auth.register.sendFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitForm(e: React.FormEvent) {
    e.preventDefault();
    if (form.password.length < 8) return setError(t("auth.register.short"));
    if (form.password !== form.password2) return setError(t("auth.register.mismatch"));
    await requestCode();
  }

  async function onSubmitCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await register({
        last_name: form.last_name,
        first_name: form.first_name,
        middle_name: form.middle_name || undefined,
        phone: form.phone,
        password: form.password,
        code,
      });
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("auth.register.failed"));
    } finally {
      setLoading(false);
    }
  }

  if (step === "code") {
    return (
      <AuthCard title={t("auth.code.title")} description={t("auth.code.description", { phone: form.phone })}>
        <form onSubmit={onSubmitCode} className="flex flex-col gap-4">
          <div className="grid gap-2">
            <Label htmlFor="code">{t("auth.code.label")}</Label>
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              required
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={loading || code.length !== 6}>
            {loading ? t("auth.code.checking") : t("auth.code.submit")}
          </Button>
          <div className="flex justify-between text-sm">
            <button
              type="button"
              className="text-muted-foreground underline-offset-4 hover:underline"
              onClick={() => {
                setStep("form");
                setCode("");
                setError(null);
              }}
            >
              {t("auth.code.edit")}
            </button>
            <button
              type="button"
              className="underline-offset-4 hover:underline disabled:text-muted-foreground disabled:no-underline"
              disabled={resendIn > 0 || loading}
              onClick={requestCode}
            >
              {resendIn > 0 ? t("auth.code.resendIn", { n: resendIn }) : t("auth.code.resend")}
            </button>
          </div>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t("auth.register.title")}
      description={t("auth.register.description")}
      footer={
        <>
          {t("auth.register.hasAccount")}{" "}
          <Link href="/login" className="underline underline-offset-4">
            {t("auth.register.toLogin")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmitForm} className="flex flex-col gap-4">
        {FIELDS.map((f) => (
          <div key={f.key} className="grid gap-2">
            <Label htmlFor={f.key}>{t(f.label)}</Label>
            <Input
              id={f.key}
              type={f.type ?? "text"}
              autoComplete={f.autoComplete}
              placeholder={f.key === "phone" ? "+7 700 000 00 00" : undefined}
              value={form[f.key]}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              required={f.required}
            />
          </div>
        ))}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={loading}>
          {loading ? t("auth.register.sending") : t("auth.register.getCode")}
        </Button>
        <p className="text-xs text-muted-foreground">{t("auth.register.parentsOnly")}</p>
      </form>
    </AuthCard>
  );
}
