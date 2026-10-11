"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import Link from "next/link";
import { signOut } from "next-auth/react";
import {
  X,
  User,
  SlidersHorizontal,
  Shield,
  Bell,
  Link2,
  Brain,
  Database,
  ExternalLink,
  Trash2,
} from "lucide-react";
import { useApp } from "./shell";
import { LinkedProviders } from "./linked-providers";
import { industries, type Preferences } from "@/lib/market";
const tabs = [
  { name: "Profile", icon: User },
  { name: "Research preferences", icon: SlidersHorizontal },
  { name: "Security", icon: Shield },
  { name: "Notifications", icon: Bell },
  { name: "Connected accounts", icon: Link2 },
  { name: "Chat memory", icon: Brain },
  { name: "Data & privacy", icon: Database },
];
export function Settings({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { preferences, savePreferences, demo } = useApp();
  const [draft, setDraft] = useState(preferences);
  const [tab, setTab] = useState("Profile");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [confirmation, setConfirmation] = useState("");
  useEffect(() => {
    if (open) {
      setDraft(preferences);
      setNotice("");
    }
  }, [open, preferences]);
  useEffect(() => {
    setRows([]);
    if (!open || demo) return;
    const url =
      tab === "Security"
        ? "/api/sessions"
        : tab === "Chat memory"
          ? "/api/service/chat-memories"
          : tab === "Connected accounts"
            ? "/api/service/broker-connections"
            : null;
    if (url)
      fetch(url)
        .then((r) => r.json())
        .then((d) => setRows(Array.isArray(d) ? d : d.data || []))
        .catch(() => setNotice("Unable to load this section."));
  }, [tab, open, demo]);
  const update = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    setDraft({ ...draft, [key]: value });
  async function action(url: string, method = "POST", body?: object) {
    setBusy(true);
    setNotice("");
    try {
      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const d = await r.json();
      if (!r.ok)
        throw new Error(d.error?.message || "Unable to complete this action.");
      if (d.url) window.location.assign(d.url);
      else setNotice(d.message || "Updated successfully.");
      return d;
    } catch (e) {
      setNotice(
        e instanceof Error ? e.message : "Unable to complete this action.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    try {
      await savePreferences(draft);
      setNotice(
        demo
          ? "Demo preferences updated for this visit."
          : "Your preferences have been saved.",
      );
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Unable to save.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="settings-modal">
          <div className="modal-heading">
            <div>
              <Dialog.Title>Make Folio yours.</Dialog.Title>
              <Dialog.Description>
                Your account, preferences, and connections.
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close settings">
              <X size={20} />
            </Dialog.Close>
          </div>
          <div className="settings-layout">
            <nav className="settings-nav" aria-label="Settings sections">
              {tabs.map(({ name, icon: Icon }) => (
                <button
                  key={name}
                  className={tab === name ? "selected" : ""}
                  onClick={() => {
                    setTab(name);
                    setNotice("");
                  }}
                >
                  <Icon size={15} />
                  {name}
                </button>
              ))}
            </nav>
            <div className="settings-content">
              <h3>{tab}</h3>
              {demo && (
                <div className="notice">
                  You’re exploring a demo. <Link href="/login">Sign in</Link> to
                  save settings and manage your account.
                </div>
              )}
              {tab === "Profile" && (
                <>
                  <p>A few details to make this space feel like yours.</p>
                  <label className="field">
                    Display name
                    <input
                      value={draft.name}
                      maxLength={80}
                      onChange={(e) => update("name", e.target.value)}
                    />
                  </label>
                  <label className="field">Appearance</label>
                  <div className="choice-row">
                    {(["light", "dark"] as const).map((t) => (
                      <button
                        className={draft.theme === t ? "selected" : ""}
                        key={t}
                        onClick={() => update("theme", t)}
                      >
                        {t === "light" ? "Light" : "Dark"}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {tab === "Research preferences" && (
                <>
                  <p>
                    Shape the research you see. Your preferences help prioritize
                    relevant ideas.
                  </p>
                  <label className="field">
                    Risk preference
                    <select
                      value={draft.risk}
                      onChange={(e) =>
                        update("risk", e.target.value as Preferences["risk"])
                      }
                    >
                      <option value="conservative">Conservative</option>
                      <option value="balanced">Balanced</option>
                      <option value="growth">Growth</option>
                    </select>
                  </label>
                  <label className="field">
                    Research horizon
                    <select
                      value={draft.horizon}
                      onChange={(e) =>
                        update(
                          "horizon",
                          e.target.value as Preferences["horizon"],
                        )
                      }
                    >
                      <option value="7d">7 days</option>
                      <option value="30d">30 days</option>
                      <option value="90d">90 days</option>
                    </select>
                  </label>
                  <label className="field">Industries you follow</label>
                  <div className="choice-row">
                    {industries.map((i) => (
                      <button
                        key={i}
                        className={
                          draft.industries.includes(i) ? "selected" : ""
                        }
                        onClick={() =>
                          update(
                            "industries",
                            draft.industries.includes(i)
                              ? draft.industries.filter((x) => x !== i)
                              : [...draft.industries, i],
                          )
                        }
                      >
                        {i}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {tab === "Notifications" && (
                <>
                  <p>
                    Choose how you hear about new research and account updates.
                  </p>
                  <Toggle
                    title="In-app research alerts"
                    description="Assessment changes and new evidence for followed stocks."
                    value={draft.inAppAlerts}
                    onChange={(v) => update("inAppAlerts", v)}
                  />
                  <Toggle
                    title="Email digest"
                    description="Research updates sent to your verified email. You can unsubscribe anytime."
                    value={draft.emailAlerts}
                    onChange={(v) => update("emailAlerts", v)}
                  />
                  <div className="notice">
                    Security emails and account recovery messages are always
                    sent when needed.
                  </div>
                </>
              )}
              {tab === "Security" && (
                <>
                  <p>Manage access to your workspace.</p>
                  <div className="setting-row">
                    <div>
                      <strong>Password</strong>
                      <p>Reset your password through a verified email link.</p>
                    </div>
                    <Link className="outline-button" href="/login?flow=forgot">
                      Reset password
                    </Link>
                  </div>
                  <LinkedProviders demo={demo} />
                  <h3 style={{ marginTop: 24 }}>Active sessions</h3>
                  {rows.map((r) => (
                    <div className="setting-row" key={r.id}>
                      <div>
                        <strong>Browser session</strong>
                        <p>Started {new Date(r.createdAt).toLocaleString()}</p>
                      </div>
                      <button
                        className="text-button danger"
                        onClick={async () => {
                          if (
                            await action("/api/sessions", "DELETE", {
                              id: r.id,
                            })
                          )
                            setRows(rows.filter((x) => x.id !== r.id));
                        }}
                      >
                        Revoke
                      </button>
                    </div>
                  ))}
                  {!rows.length && (
                    <p className="muted">No sessions to display.</p>
                  )}
                </>
              )}
              {tab === "Connected accounts" && (
                <>
                  <p>
                    Bring your positions into focus. Account access is used for
                    research only.
                  </p>
                  <div className="setting-row">
                    <div>
                      <strong>Robinhood</strong>
                      <p>
                        {rows.length
                          ? "Connected · holdings access"
                          : "Connect equities and portfolio balances"}
                      </p>
                    </div>
                    <button
                      className="outline-button"
                      disabled={demo || busy}
                      onClick={() =>
                        void action(
                          "/api/service/broker-connections/robinhood/start",
                        )
                      }
                    >
                      Connect <ExternalLink size={13} />
                    </button>
                  </div>
                  {rows.map((r) => (
                    <div className="setting-row" key={r.id}>
                      <strong>{r.name || "Robinhood account"}</strong>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          void action(
                            `/api/service/broker-connections/${r.id}`,
                            "DELETE",
                          )
                        }
                      >
                        Disconnect
                      </button>
                    </div>
                  ))}
                  <div className="notice">
                    Robinhood connection becomes available when this application
                    is approved. Your brokerage password is never collected
                    here.
                  </div>
                </>
              )}
              {tab === "Chat memory" && (
                <>
                  <p>
                    Your conversations disappear when you leave. With your
                    permission, Folio can remember a small set of research
                    preferences.
                  </p>
                  <Toggle
                    title="Remember research preferences"
                    description="Save interests, horizon, and presentation preferences across conversations."
                    value={draft.memory}
                    onChange={(v) => update("memory", v)}
                  />
                  {rows.map((r) => (
                    <div className="setting-row" key={r.key}>
                      <div>
                        <strong>{r.key.replaceAll("_", " ")}</strong>
                        <input
                          aria-label={`Edit memory ${r.key}`}
                          value={r.value}
                          maxLength={200}
                          onChange={(event) =>
                            setRows(
                              rows.map((entry) =>
                                entry.key === r.key
                                  ? { ...entry, value: event.target.value }
                                  : entry,
                              ),
                            )
                          }
                        />
                      </div>
                      <button
                        className="outline-button"
                        disabled={busy || !r.value.trim()}
                        onClick={() =>
                          void action("/api/service/chat-memories", "PATCH", {
                            key: r.key,
                            value: r.value.trim(),
                          })
                        }
                      >
                        Save
                      </button>
                      <button
                        className="icon-button"
                        aria-label={`Delete memory ${r.key}`}
                        onClick={async () => {
                          if (
                            await action(
                              "/api/service/chat-memories",
                              "DELETE",
                              { key: r.key },
                            )
                          )
                            setRows(rows.filter((x) => x.key !== r.key));
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                  {!rows.length && (
                    <div className="notice">
                      No saved memories yet. Account numbers, passwords, and
                      conversations are never stored as memory.
                    </div>
                  )}
                  <button
                    className="outline-button"
                    disabled={demo || busy}
                    onClick={async () => {
                      if (await action("/api/service/chat-memories", "DELETE"))
                        setRows([]);
                    }}
                  >
                    Clear all memories
                  </button>
                </>
              )}
              {tab === "Data & privacy" && (
                <>
                  <p>
                    You control your account information and saved research
                    context.
                  </p>
                  <button
                    className="outline-button"
                    disabled={demo}
                    onClick={async () => {
                      const r = await fetch("/api/export");
                      if (!r.ok) {
                        setNotice("Export unavailable. Please try again.");
                        return;
                      }
                      const blob = await r.blob();
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = "folio-account.json";
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Export my data
                  </button>
                  <div className="notice">
                    Chat transcripts are not stored by Folio. AI requests are
                    processed by the configured inference provider; its
                    retention terms also apply.
                  </div>
                  <h3 style={{ marginTop: 25 }}>Delete account</h3>
                  <p className="muted">
                    Deletes your profile, saved memories, and portfolio records.
                    Type DELETE to confirm.
                  </p>
                  <label className="field">
                    Confirmation
                    <input
                      value={confirmation}
                      onChange={(e) => setConfirmation(e.target.value)}
                    />
                  </label>
                  <button
                    className="outline-button danger"
                    disabled={demo || confirmation !== "DELETE" || busy}
                    onClick={async () => {
                      if (
                        await action("/api/account", "DELETE", { confirmation })
                      )
                        void signOut({ callbackUrl: "/" });
                    }}
                  >
                    Delete my account
                  </button>
                </>
              )}
            </div>
          </div>
          <div className="modal-footer">
            <span role="status">
              {notice || "Your workspace. Your preferences."}
            </span>
            <button
              className="primary-button"
              disabled={busy || !draft.name.trim()}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save preferences"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
function Toggle({
  title,
  description,
  value,
  onChange,
}: {
  title: string;
  description: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-label={title}
        aria-checked={value}
        className={`toggle ${value ? "on" : ""}`}
        onClick={() => onChange(!value)}
      >
        <span />
      </button>
    </div>
  );
}
