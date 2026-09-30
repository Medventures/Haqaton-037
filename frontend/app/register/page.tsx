"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, register, sendRegisterCode } from "@/lib/api";

type Form = {
  last_name: string;
  first_name: string;
  middle_name: string;
  phone: string;
  password: string;
  password2: string;
};

const FIELDS: { key: keyof Form; label: string; type?: string; autoComplete: string; required: boolean }[] = [
  { key: "last_name", label: "Фамилия", autoComplete: "family-name", required: true },
  { key: "first_name", label: "Имя", autoComplete: "given-name", required: true },
  { key: "middle_name", label: "Отчество (если есть)", autoComplete: "additional-name", required: false },
  { key: "phone", label: "Телефон", type: "tel", autoComplete: "tel", required: true },
  { key: "password", label: "Пароль (минимум 8 символов)", type: "password", autoComplete: "new-password", required: true },
  { key: "password2", label: "Повторите пароль", type: "password", autoComplete: "new-password", required: true },
];

export default function RegisterPage() {
  const router = useRouter();
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
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  async function requestCode() {
    setError(null);
    setLoading(true);
    try {
      const res = await sendRegisterCode(form.phone);
      setResendIn(res.resend_in);
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить код");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitForm(e: React.FormEvent) {
    e.preventDefault();
    if (form.password.length < 8) return setError("Пароль должен быть не короче 8 символов");
    if (form.password !== form.password2) return setError("Пароли не совпадают");
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
      setError(err instanceof ApiError ? err.message : "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  }

  if (step === "code") {
    return (
      <AuthCard title="Подтверждение номера" description={`Мы отправили SMS с кодом на ${form.phone}`}>
        <form onSubmit={onSubmitCode} className="flex flex-col gap-4">
          <div className="grid gap-2">
            <Label htmlFor="code">Код из SMS</Label>
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
            {loading ? "Проверяем…" : "Подтвердить"}
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
              Изменить данные
            </button>
            <button
              type="button"
              className="underline-offset-4 hover:underline disabled:text-muted-foreground disabled:no-underline"
              disabled={resendIn > 0 || loading}
              onClick={requestCode}
            >
              {resendIn > 0 ? `Отправить снова через ${resendIn} с` : "Отправить код снова"}
            </button>
          </div>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Регистрация"
      description="Номер телефона подтверждается кодом из SMS"
      footer={
        <>
          Уже есть аккаунт?{" "}
          <Link href="/login" className="underline underline-offset-4">
            Войти
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmitForm} className="flex flex-col gap-4">
        {FIELDS.map((f) => (
          <div key={f.key} className="grid gap-2">
            <Label htmlFor={f.key}>{f.label}</Label>
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
          {loading ? "Отправляем код…" : "Получить код"}
        </Button>
      </form>
    </AuthCard>
  );
}
