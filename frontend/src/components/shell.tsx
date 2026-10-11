"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import {
  Home,
  Flame,
  Layers3,
  ArrowUpRight,
  ChevronDown,
  Plus,
  Send,
  Sun,
  Moon,
  Sparkles,
  ArrowRight,
  Activity,
  PanelRight,
  LogOut,
} from "lucide-react";
import { defaultPreferences, type Preferences } from "@/lib/market";
import { Settings } from "./settings";
import { Notifications } from "./notifications";
type AppContext = {
  preferences: Preferences;
  savePreferences: (p: Preferences) => Promise<void>;
  demo: boolean;
  openSettings: () => void;
};
const Context = createContext<AppContext>(null!);
export const useApp = () => useContext(Context);
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data: session, status } = useSession();
  const demo = !session;
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [settings, setSettings] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  useEffect(() => {
    if (session) {
      fetch("/api/account")
        .then((r) => (r.ok ? r.json() : null))
        .then((p) => {
          if (p?.preferences)
            setPreferences({
              ...defaultPreferences,
              ...p.preferences,
              name: session.user?.name || "Your account",
            });
        });
    } else if (status === "unauthenticated") {
      const theme = localStorage.getItem("folio-theme");
      setPreferences({
        ...defaultPreferences,
        theme: theme === "dark" ? "dark" : "light",
      });
    }
  }, [session, status]);
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    localStorage.setItem("folio-theme", preferences.theme);
  }, [preferences.theme]);
  async function savePreferences(p: Preferences) {
    if (!demo) {
      const r = await fetch("/api/account", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences: p }),
      });
      if (!r.ok)
        throw new Error(
          "Your preferences could not be saved. Please try again.",
        );
    }
    setPreferences(p);
  }
  return (
    <Context.Provider
      value={{
        preferences,
        savePreferences,
        demo,
        openSettings: () => setSettings(true),
      }}
    >
      <div className={`app-shell ${!chatOpen ? "chat-hidden" : ""}`}>
        <aside className="nav-rail">
          <Link href="/" className="brand">
            <span className="brand-icon">
              <Activity size={21} />
            </span>
            folio<span className="brand-dot">.</span>
          </Link>
          <div className="workspace-label">YOUR WORKSPACE</div>
          <nav aria-label="Main navigation">
            {[
              { href: "/", name: "Home", icon: Home },
              { href: "/trending", name: "Trending", icon: Flame },
              { href: "/industries", name: "Industries", icon: Layers3 },
            ].map(({ href, name, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                aria-current={
                  (href === "/" ? path === "/" : path.startsWith(href))
                    ? "page"
                    : undefined
                }
                className={`nav-item ${(href === "/" && path === "/") || (href !== "/" && path.startsWith(href)) ? "active" : ""}`}
              >
                <Icon size={19} />
                <span>{name}</span>
                {name === "Trending" && <span className="nav-count">05</span>}
              </Link>
            ))}
          </nav>
          <div className="nav-note">
            <div className="mini-orbit">✳</div>
            <h3>A little more perspective.</h3>
            <p>Understand the stories behind your investments.</p>
            <Link href="/industries">
              Explore the market <ArrowUpRight size={15} />
            </Link>
          </div>
          <div className="nav-bottom">
            <div className="system-status">
              <span className="status-dot" />
              {demo ? "Demo workspace" : "Your workspace"}
              <button
                aria-label="Toggle color theme"
                className="icon-button"
                onClick={() =>
                  void savePreferences({
                    ...preferences,
                    theme: preferences.theme === "light" ? "dark" : "light",
                  })
                }
              >
                {preferences.theme === "light" ? (
                  <Moon size={16} />
                ) : (
                  <Sun size={16} />
                )}
              </button>
            </div>
            <button
              className="account-button"
              onClick={() => setSettings(true)}
            >
              <span className="avatar">
                {preferences.name
                  .split(" ")
                  .map((x) => x[0])
                  .slice(0, 2)
                  .join("")}
              </span>
              <span>
                <strong>{preferences.name}</strong>
                <small>{demo ? "Explore demo" : "Account settings"}</small>
              </span>
              <ChevronDown size={15} />
            </button>
            {!demo && (
              <button
                className="text-button signout"
                onClick={() => void signOut({ callbackUrl: "/" })}
              >
                <LogOut size={14} /> Sign out
              </button>
            )}
          </div>
        </aside>
        <main className="workspace">
          <div className="topbar">
            <div className="breadcrumb">
              Workspace <span>/</span>{" "}
              {path.startsWith("/trending")
                ? "Trending"
                : path.startsWith("/industries")
                  ? "Industries"
                  : path.startsWith("/stocks")
                    ? "Stock research"
                    : "Overview"}
            </div>
            <div className="topbar-actions">
              <Notifications demo={demo} />
              {demo ? (
                <Link href="/login" className="text-button">
                  Sign in <ArrowUpRight size={14} />
                </Link>
              ) : (
                <span className="muted">Personal workspace</span>
              )}
              <button
                className="icon-button"
                aria-label="Toggle research assistant"
                onClick={() => setChatOpen(!chatOpen)}
              >
                <PanelRight size={18} />
              </button>
            </div>
          </div>
          {demo && (
            <div className="demo-banner">
              <span className="small-dot" />
              Demo workspace · Illustrative market data as of Oct 10, 2026
              <Link href="/login">
                Connect your portfolio <ArrowRight size={13} />
              </Link>
            </div>
          )}
          <div className="page-content">{children}</div>
          <footer className="workspace-footer">
            Made for a more informed perspective.
            <span>Research insights. No trade execution.</span>
          </footer>
        </main>
        {chatOpen && <Chat />}
      </div>
      <Settings open={settings} onOpenChange={setSettings} />
    </Context.Provider>
  );
}
type Message = {
  role: "user" | "assistant";
  content: string;
  citations?: { symbol: string; label: string }[];
};
function Chat() {
  const { demo, preferences } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);
  useEffect(
    () => () => {
      request.current?.abort();
    },
    [],
  );
  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    setError("");
    const next = [...messages, { role: "user" as const, content: text.trim() }];
    setMessages(next);
    setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, context: next.slice(-10), demo }),
        signal: controller.signal,
      });
      const data = await r.json();
      if (!r.ok)
        throw new Error(
          data.error?.message || "The assistant is temporarily unavailable.",
        );
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data.reply, citations: data.citations },
      ]);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Unable to reach the assistant.",
        );
    } finally {
      setBusy(false);
    }
  }
  return (
    <aside className="chat-rail" aria-label="Research assistant">
      <div className="chat-header">
        <span className="assistant-icon">
          <Sparkles size={18} />
        </span>
        <div>
          <strong>Folio assistant</strong>
          <small>Your research companion</small>
        </div>
        <button
          className="icon-button"
          aria-label="New conversation"
          onClick={() => {
            request.current?.abort();
            setMessages([]);
            setError("");
            setBusy(false);
          }}
        >
          <Plus size={19} />
        </button>
      </div>
      <div className="chat-body">
        {messages.length === 0 ? (
          <>
            <div className="chat-welcome">
              <span className="welcome-spark">
                <Sparkles size={25} />
              </span>
              <h2>
                A clearer view
                <br />
                starts with a question.
              </h2>
              <p>
                Connect the dots between your portfolio and what’s happening in
                the market.
              </p>
            </div>
            <div className="prompt-label">A FEW PLACES TO START</div>
            {[
              "Give me a portfolio overview",
              "What’s driving technology stocks?",
              "Where am I most concentrated?",
            ].map((p) => (
              <button
                className="prompt-card"
                key={p}
                onClick={() => void send(p)}
              >
                {p}
                <ArrowUpRight size={15} />
              </button>
            ))}
            <div className="chat-context">
              <span className="status-dot" />
              <span>
                {demo
                  ? "Using sample research"
                  : preferences.memory
                    ? "Your research preferences are remembered"
                    : "Chat memory is off"}
              </span>
            </div>
          </>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`}>
              <span className="message-author">
                {m.role === "assistant" ? "✳ Folio" : "You"}
              </span>
              <p>{m.content}</p>
              {m.citations?.map((c) => (
                <Link
                  className="citation"
                  key={c.symbol}
                  href={`/stocks/${c.symbol}`}
                >
                  {c.label}
                  <ArrowUpRight size={12} />
                </Link>
              ))}
            </div>
          ))
        )}
        {busy && (
          <div role="status" className="thinking">
            Connecting the dots<span>•••</span>
          </div>
        )}
        {error && (
          <div role="alert" className="error-box">
            {error}
            <button
              className="text-button"
              onClick={() => void send(messages.at(-1)?.content || "Overview")}
            >
              Retry
            </button>
          </div>
        )}
        <div ref={bottom} />
      </div>
      <div className="chat-composer">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <textarea
            aria-label="Ask Folio a question"
            placeholder="Ask anything about the market…"
            value={input}
            maxLength={4000}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
          />
          <div className="composer-bottom">
            <span>
              <Sparkles size={12} /> {demo ? "Demo research" : "Research mode"}
            </span>
            <button aria-label="Send message" disabled={busy || !input.trim()}>
              <Send size={15} />
            </button>
          </div>
        </form>
        <p>
          AI can make mistakes. Check the sources.
          <br />
          Conversations aren’t saved.
        </p>
      </div>
    </aside>
  );
}
