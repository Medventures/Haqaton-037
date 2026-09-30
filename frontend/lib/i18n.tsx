"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { DICT, type Key } from "@/lib/dictionary";
import { cn } from "@/lib/utils";

export type Lang = "ru" | "kk";
export type T = (key: Key, vars?: Record<string, string | number>) => string;

const STORAGE_KEY = "aqyl_lang";
const listeners = new Set<() => void>();
let memory: Lang = "ru"; // used when localStorage is unavailable

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function read(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "kk" || stored === "ru" ? stored : memory;
  } catch {
    return memory;
  }
}

function write(lang: Lang) {
  memory = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {}
  listeners.forEach((l) => l());
}

/** The interface language, remembered per browser. Russian during server rendering. */
export function useLang(): [Lang, (lang: Lang) => void] {
  const lang = useSyncExternalStore(subscribe, read, () => "ru" as Lang);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  return [lang, write];
}

/** The current language outside React (API client). */
export function currentLang(): Lang {
  return typeof window === "undefined" ? "ru" : read();
}

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let text = DICT[lang][key];
  for (const [name, value] of Object.entries(vars ?? {})) text = text.replaceAll(`{${name}}`, String(value));
  return text;
}

export function useT(): T {
  const [lang] = useLang();
  return useCallback((key, vars) => translate(lang, key, vars), [lang]);
}

/** The Kazakh field from the API when the interface is Kazakh and it exists; otherwise Russian. */
export function pick(lang: Lang, ru: string, kk?: string | null): string {
  return lang === "kk" && kk ? kk : ru;
}

export function LanguageSwitch({ className }: { className?: string }) {
  const [lang, setLang] = useLang();
  return (
    <div className={cn("inline-flex rounded-lg border p-0.5 text-xs font-medium", className)} role="group" aria-label="Язык / Тіл">
      {(["ru", "kk"] as const).map((l) => (
        <button
          key={l}
          type="button"
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
          className={cn(
            "rounded-md px-2 py-1",
            lang === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {DICT[l][`lang.${l}`]}
        </button>
      ))}
    </div>
  );
}
