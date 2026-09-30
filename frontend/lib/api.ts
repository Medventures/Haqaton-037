const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "aqylroute_token";

export type User = {
  id: number;
  last_name: string;
  first_name: string;
  middle_name: string | null;
  phone: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  user: User;
};

export type SendCodeResponse = {
  sent: boolean;
  resend_in: number;
  expires_in: number;
};

export type RegisterInput = {
  last_name: string;
  first_name: string;
  middle_name?: string;
  phone: string;
  password: string;
  code: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
}

function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI 422 validation errors: [{ msg: "..." }]
  if (Array.isArray(detail) && detail[0]?.msg) {
    return String(detail[0].msg).replace(/^Value error, /, "");
  }
  return status >= 500 ? "Сервер недоступен. Попробуйте позже." : "Ошибка запроса";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Нет связи с сервером", 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
  return body as T;
}

export function sendRegisterCode(phone: string) {
  return request<SendCodeResponse>("/auth/register/send-code", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export async function register(input: RegisterInput): Promise<User> {
  const data = await request<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  setToken(data.access_token);
  return data.user;
}

export async function login(phone: string, password: string): Promise<User> {
  const data = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ phone, password }),
  });
  setToken(data.access_token);
  return data.user;
}

export function getMe() {
  return request<User>("/auth/me");
}

// ---------------------------------------------------------------------------
// Cases, interview, plans. Shapes mirror backend/schemas.py.

export type CaseStatus = "interview" | "draft" | "approved";
export type StepStatus = "todo" | "in_progress" | "done" | "blocked";
export type OverdueLevel = 0 | 1 | 2;

export type Case = {
  id: number;
  label: string;
  status: CaseStatus;
  created_at: string;
};

export type QuestionKind = "choice" | "multi" | "age" | "months" | "text";

export type Question = {
  slot: string;
  group_id: string;
  text: string;
  hint: string;
  kind: QuestionKind;
  options: string[];
  dont_know_label: string;
};

export type InterviewState = {
  case: Case;
  question: Question | null;
  answered: number;
  min_questions: number;
  max_questions: number;
  done: boolean;
};

/** Exactly one of dont_know, option, options, value (months), text. */
export type Answer = { slot: string } & (
  | { dont_know: true }
  | { option: number }
  | { options: number[] }
  | { value: number }
  | { text: string }
);

export type PlanDocument = {
  doc_code: string;
  title: string;
  on_hand: boolean;
  from_step: string | null;
  auto_fetch: string | null;
};

export type PlanStep = {
  step_id: string;
  service_id: string;
  title: string;
  sector: string;
  responsible: string;
  channel: string[];
  depends_on: string[];
  documents: PlanDocument[];
  legal_source: string;
  legal_url: string | null;
  due_date: string;
  deadline_note: string;
  status: StepStatus;
  priority: number;
  rationale: string;
  parent_explanation: string;
  text_source: "ai" | "fallback";
  warning: string | null;
  days_overdue: number;
  overdue_level: OverdueLevel;
};

export type OverdueSummary = {
  steps_total: number;
  steps_done: number;
  overdue_count: number;
  worst_level: OverdueLevel;
};

export type Plan = {
  id: number;
  case_id: number;
  case_status: CaseStatus;
  plan: {
    start_date: string;
    generated_at: string;
    generator: "ai" | "fallback";
    model: string | null;
    steps: PlanStep[];
    undecided: string[];
  };
  overdue: OverdueSummary;
  today: string;
  updated_at: string;
};

export type CuratorLoad = {
  active_cases: number;
  norm_min: number;
  norm_max: number;
  state: "below" | "within" | "above";
  norm_source: string;
};

export type CaseSummary = Case & OverdueSummary & { parent_name: string; plan_id: number | null };

export type CaseList = { cases: CaseSummary[]; load: CuratorLoad; today: string };

export type InterviewAnswer = {
  slot: string;
  question_text: string;
  raw_answer: string;
  parsed: Record<string, unknown>;
  created_at: string;
};

export type CaseEvent = {
  id: number;
  kind: string;
  step_id: string | null;
  actor_user_id: number | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type CaseDetail = {
  case: Case;
  parent_name: string;
  facts: Record<string, unknown>;
  answers: InterviewAnswer[];
  plan: Plan | null;
  events: CaseEvent[];
};

export type ParentStep = Omit<PlanStep, "service_id" | "sector" | "depends_on" | "rationale" | "text_source">;

export type ParentPlan = { case: Case; steps: ParentStep[]; overdue: OverdueSummary; today: string };

export type Service = {
  service_id: string;
  title: string;
  sector: string;
  responsible: string;
  mode: "direct" | "prerequisite" | "trigger";
  sla_days: number | null;
  sla_unit: string | null;
  priority_default: number;
  depends_on: string[];
  ui_note: string | null;
};

export type StepPatch = Partial<{ status: StepStatus; priority: 1 | 2 | 3; due_date: string }>;

export type Escalation = {
  step_id: string;
  recipient: string;
  days_overdue: number;
  overdue_level: OverdueLevel;
  warning: string | null;
  message: string;
};

function withToday(path: string, today?: string) {
  return today ? `${path}${path.includes("?") ? "&" : "?"}today=${today}` : path;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});

// Parent
export const createCase = (label: string) => request<InterviewState>("/cases", post({ label }));
export const getInterview = (caseId: number) => request<InterviewState>(`/cases/${caseId}/interview`);
export const sendAnswer = (caseId: number, answer: Answer) =>
  request<InterviewState>(`/cases/${caseId}/answers`, post(answer));
export const myCases = () => request<Case[]>("/parent/cases");
export const myPlan = (caseId: number) => request<ParentPlan>(`/parent/cases/${caseId}`);

// Plan generation (parent after the interview, curator to regenerate)
export const generatePlan = (caseId: number, regenerate = false) =>
  request<Plan>(`/cases/${caseId}/plan${regenerate ? "?regenerate=true" : ""}`, post());

// Curator
export const listCases = (today?: string) => request<CaseList>(withToday("/cases", today));
export const caseDetail = (caseId: number, today?: string) =>
  request<CaseDetail>(withToday(`/cases/${caseId}`, today));
export const updateStep = (planId: number, stepId: string, patch: StepPatch, today?: string) =>
  request<Plan>(withToday(`/plans/${planId}/steps/${stepId}`, today), {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
export const addStep = (planId: number, serviceId: string, today?: string) =>
  request<Plan & { added: string[] }>(withToday(`/plans/${planId}/steps`, today), post({ service_id: serviceId }));
export const approvePlan = (planId: number, today?: string) =>
  request<Plan>(withToday(`/plans/${planId}/approve`, today), post());
export const escalateStep = (planId: number, stepId: string, today?: string) =>
  request<Escalation>(withToday(`/plans/${planId}/steps/${stepId}/escalate`, today), post());
export const listServices = () => request<Service[]>("/services");
