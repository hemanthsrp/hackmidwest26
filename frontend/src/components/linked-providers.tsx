"use client";
import { useEffect, useState } from "react";
import { getProviders, signIn } from "next-auth/react";
export function LinkedProviders({ demo }: { demo: boolean }) {
  const [linked, setLinked] = useState<string[]>([]);
  const [available, setAvailable] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    getProviders().then((p) => setAvailable(Object.keys(p || {})));
    if (!demo)
      fetch("/api/providers")
        .then((r) => r.json())
        .then((rows) => {
          if (Array.isArray(rows)) setLinked(rows.map((x) => x.provider));
        });
  }, [demo]);
  return (
    <>
      <h3 style={{ marginTop: 22 }}>Sign-in methods</h3>
      {[
        ["google", "Google"],
        ["apple", "Apple"],
        ["microsoft-entra-id", "Microsoft"],
      ].map(([id, name]) => (
        <div className="setting-row" key={id}>
          <strong>{name}</strong>
          {linked.includes(id) ? (
            <button
              className="text-button danger"
              onClick={async () => {
                const r = await fetch("/api/providers", {
                  method: "DELETE",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ provider: id }),
                });
                const d = await r.json();
                setNotice(d.message || d.error?.message);
                if (r.ok) setLinked(linked.filter((x) => x !== id));
              }}
            >
              Disconnect
            </button>
          ) : (
            <button
              className="outline-button"
              disabled={demo || !available.includes(id)}
              onClick={() => void signIn(id, { callbackUrl: "/" })}
            >
              Connect
            </button>
          )}
        </div>
      ))}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
    </>
  );
}
