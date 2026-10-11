"use client";
import Link from "next/link";
import { signIn, getProviders } from "next-auth/react";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Activity, ArrowRight, ArrowUpRight } from "lucide-react";
function Login() {
  const params = useSearchParams();
  const [flow, setFlow] = useState(params.get("flow") || "login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<string[]>([]);
  useEffect(() => {
    getProviders().then((p) => setProviders(Object.keys(p || {})));
  }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (flow === "login") {
        const result = await signIn("credentials", {
          email,
          password,
          redirect: false,
        });
        if (result?.error)
          setMessage(
            "Unable to sign in. Check your credentials and verify your email.",
          );
        else window.location.assign("/");
      } else {
        const r = await fetch("/api/identity", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: flow,
            email: email || undefined,
            password: password || undefined,
            name: name || undefined,
            token: params.get("token") || undefined,
          }),
        });
        const d = await r.json();
        setMessage(
          d.message || d.error?.message || "Unable to complete this request.",
        );
      }
    } catch {
      setMessage("Unable to reach account services. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  const title: Record<string, string> = {
    login: "Welcome back.",
    register: "Make the market yours.",
    forgot: "Reset your password.",
    reset: "A fresh start.",
    verify: "Verify your email.",
    resend: "Resend verification.",
  };
  return (
    <div className="auth-page">
      <div className="auth-story">
        <Link className="brand" href="/">
          <span className="brand-icon">
            <Activity size={20} />
          </span>
          folio.
        </Link>
        <div>
          <span className="eyebrow">YOUR MARKET, IN PERSPECTIVE</span>
          <h1>
            Less noise.
            <br />
            More understanding.
          </h1>
          <p>
            A thoughtful space for your investments, the stories behind them,
            and the questions that matter.
          </p>
          <Link href="/" className="text-button" style={{ marginTop: 25 }}>
            Explore the demo <ArrowUpRight size={15} />
          </Link>
        </div>
        <div>
          <small>Source-backed research. A broader perspective.</small>
          <div className="legal-links auth-legal-links">
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
          </div>
        </div>
      </div>
      <div className="auth-form">
        <div className="auth-box">
          <span className="eyebrow">WELCOME TO FOLIO</span>
          <h2>{title[flow] || title.login}</h2>
          <p>
            {flow === "login"
              ? "Sign in to pick up where you left off."
              : flow === "register"
                ? "Create an account to bring your research together."
                : "Follow the steps below to manage your account."}
          </p>
          {["login", "register"].includes(flow) && (
            <>
              <div className="oauth-buttons">
                {[
                  ["google", "Google"],
                  ["apple", "Apple"],
                  ["microsoft-entra-id", "Microsoft"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    disabled={!providers.includes(id)}
                    title={
                      providers.includes(id)
                        ? `Continue with ${label}`
                        : `${label} sign-in is not configured`
                    }
                    onClick={() => void signIn(id, { callbackUrl: "/" })}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="separator">or continue with email</div>
            </>
          )}
          <form onSubmit={submit}>
            {flow === "register" && (
              <label className="field">
                Full name
                <input
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  maxLength={80}
                />
              </label>
            )}
            {!["verify", "reset"].includes(flow) && (
              <label className="field">
                Email address
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                />
              </label>
            )}
            {["login", "register", "reset"].includes(flow) && (
              <label className="field">
                Password
                <input
                  required
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={flow === "login" ? 1 : 12}
                  maxLength={128}
                  autoComplete={
                    flow === "login" ? "current-password" : "new-password"
                  }
                />
                {flow !== "login" && (
                  <small style={{ marginTop: 7 }}>
                    Use at least 12 characters.
                  </small>
                )}
              </label>
            )}
            <button className="primary-button" disabled={busy}>
              {busy
                ? "Working…"
                : flow === "login"
                  ? "Sign in"
                  : flow === "register"
                    ? "Create account"
                    : flow === "verify"
                      ? "Verify email"
                      : "Continue"}
              <ArrowRight size={15} />
            </button>
          </form>
          {message && (
            <div role="status" className="notice">
              {message}
            </div>
          )}
          <div className="auth-links">
            <button
              className="text-button"
              onClick={() => {
                setFlow(flow === "login" ? "register" : "login");
                setMessage("");
              }}
            >
              {flow === "login" ? "Create an account" : "Back to sign in"}
            </button>
            {flow === "login" && (
              <button className="text-button" onClick={() => setFlow("forgot")}>
                Forgot password?
              </button>
            )}
          </div>
          {flow === "login" && (
            <button className="text-button" onClick={() => setFlow("resend")}>
              Resend verification email
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
export default function Page() {
  return (
    <Suspense fallback={<div className="empty-state">Loading…</div>}>
      <Login />
    </Suspense>
  );
}
