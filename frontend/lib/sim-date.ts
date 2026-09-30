"use client";

import { useSyncExternalStore } from "react";

const KEY = "aqylroute_sim_date";

/** The seed's demo date: the most recent 11 September (12 days after the 30 August school deadline). */
export function demoDate(now = new Date()): string {
  const passed = now.getMonth() > 8 || (now.getMonth() === 8 && now.getDate() >= 11);
  return `${passed ? now.getFullYear() : now.getFullYear() - 1}-09-11`;
}

export function realToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const listeners = new Set<() => void>();
let memory: string | null = null; // used when localStorage is unavailable

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? memory ?? demoDate();
  } catch {
    return memory ?? demoDate();
  }
}

function write(date: string) {
  memory = date;
  try {
    localStorage.setItem(KEY, date);
  } catch {}
  listeners.forEach((l) => l());
}

/**
 * «Симулировать дату»: the curator's date for overdue, passed to the API as ?today=.
 * Remembered per browser and shared by the curator pages; null during server rendering.
 */
export function useSimDate(): [string | null, (date: string) => void] {
  const date = useSyncExternalStore(subscribe, read, () => null);
  return [date, write];
}
