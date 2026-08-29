"use client";

import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import type { Language, Mode } from "@/lib/types";
import { t } from "@/lib/i18n";

const field =
"w-full  border border-border bg-bg px-3.5 py-2.5 text-base text-fg outline-none transition-colors focus:border-border-strong placeholder:text-fg-faint";
const btn =
"w-full rounded-full bg-accent px-4 py-2.5 font-medium text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-60";

/**
 * Where to send someone after they sign in.
 *
 * `next` arrives in a query string, so it is attacker-controllable: an
 * absolute URL or a protocol-relative `//evil.example` would turn our own login
 * form into an open redirect. Only a single-slash, same-origin path is honoured;
 * anything else falls back to the project list.
 */
function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/app/projects";
  return raw;
}

export function LoginForm({ language }: { language: Language }) {
  const router = useRouter();
  // Middleware bounces an unauthenticated request here with `?next=` set to
  // where the user was actually going. Landing them on the project list instead
  // would silently discard a deep link — a shared chat URL, a dataset page —
  // which is the most annoying possible outcome of asking someone to sign in.
  const next = safeNext(useSearchParams()?.get("next"));
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await fetch("/api/session/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, password }),
    });
    setLoading(false);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.error ?? "Login failed");
      return;
    }
    router.push(next);
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {error && <p className=" border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      <input className={field} placeholder={t("phone", language)} value={phone}
        onChange={(e) => setPhone(e.target.value)} autoComplete="tel" required />
      <input className={field} type="password" placeholder={t("password", language)} value={password}
        onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      <button className={btn} disabled={loading}>{t("login", language)}</button>
      <p className="text-center text-sm text-fg-muted">
        {t("noAccount", language)}{" "}
        <Link href="/auth/register" className="text-accent hover:underline">
          {t("register", language)}
        </Link>
      </p>
    </form>
  );
}

export function RegisterForm({ language, initialMode }: { language: Language; initialMode: Mode }) {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Mode>(initialMode);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await fetch("/api/session/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, password, email: email || null, role, preferred_language: language }),
    });
    setLoading(false);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.error ?? "Registration failed");
      return;
    }
    // Straight to onboarding, not to the dashboard. Middleware would redirect
    // there anyway; going directly saves a round trip and, more importantly,
    // removes the frame in which the app shell paints behind the redirect.
    router.push("/onboarding");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {error && <p className=" border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="inline-flex rounded-full border border-border bg-surface-2 p-0.5">
        {(["student", "researcher"] as Mode[]).map((m) => (
          <button type="button" key={m} onClick={() => setRole(m)}
            className={`rounded-full px-4 py-1.5 text-sm transition-colors ${role === m ? "bg-accent text-accent-fg" : "text-fg-muted hover:text-fg"}`}>
            {t(m, language)}
          </button>
        ))}
      </div>
      <input className={field} placeholder={t("phone", language)} value={phone}
        onChange={(e) => setPhone(e.target.value)} autoComplete="tel" required />
      <input className={field} type="password" placeholder={t("password", language)} value={password}
        onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={8} required />
      <input className={field} type="email" placeholder={t("email", language)} value={email}
        onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
      <button className={btn} disabled={loading}>{t("register", language)}</button>
      <p className="text-center text-sm text-fg-muted">
        {t("haveAccount", language)}{" "}
        <Link href="/auth/login" className="text-accent hover:underline">
          {t("login", language)}
        </Link>
      </p>
    </form>
  );
}

export function OtpForm({ language }: { language: Language }) {
  const router = useRouter();
  const next = safeNext(useSearchParams()?.get("next"));
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const res = await fetch("/api/session/otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "request", phone }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setError(data.error ?? "could not send code");
    setSent(true);
    if (data.dev_code) setDevCode(data.dev_code);
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const res = await fetch("/api/session/otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "verify", phone, code }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return setError(data.error ?? "verification failed");
    }
    router.push(next);
    router.refresh();
  }

  return (
    <div className="space-y-3">
      {error && <p className=" border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      {!sent ? (
        <form onSubmit={requestCode} className="space-y-3">
          <input className={field} placeholder={t("phone", language)} value={phone}
            onChange={(e) => setPhone(e.target.value)} autoComplete="tel" required />
          <button className={btn}>{language === "sw" ? "Tuma namba ya siri" : "Send code"}</button>
        </form>
      ) : (
        <form onSubmit={verify} className="space-y-3">
          {devCode && (
            <p className=" border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-warn">
              Dev code: <strong>{devCode}</strong>
            </p>
          )}
          <input className={field} inputMode="numeric" placeholder="123456" value={code}
            onChange={(e) => setCode(e.target.value)} required />
          <button className={btn}>{t("verifyOtp", language)}</button>
        </form>
      )}
    </div>
  );
}
