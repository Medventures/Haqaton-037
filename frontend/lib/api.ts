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
