"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, X } from "lucide-react";
import Link from "next/link";
export function Notifications({ demo }: { demo: boolean }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["notifications"],
    enabled: open && !demo,
    queryFn: async () => {
      const r = await fetch("/api/service/notifications");
      if (!r.ok) throw new Error("Notifications are unavailable.");
      return r.json();
    },
  });
  return (
    <div className="notification-anchor">
      <button
        className="icon-button"
        aria-label="Notifications"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Bell size={17} />
      </button>
      {open && (
        <div className="notification-popover">
          <div className="card-row">
            <h3>Notifications</h3>
            <button
              className="icon-button"
              aria-label="Close notifications"
              onClick={() => setOpen(false)}
            >
              <X size={14} />
            </button>
          </div>
          {demo ? (
            <p>Sign in to receive research updates for your portfolio.</p>
          ) : q.isPending ? (
            <p>Loading…</p>
          ) : q.isError ? (
            <p>{q.error.message}</p>
          ) : q.data?.data?.length ? (
            q.data.data.map(
              (row: {
                key: string;
                value: {
                  title: string;
                  body: string;
                  symbol: string;
                  read: boolean;
                };
              }) => (
                <div className="evidence" key={row.key}>
                  <Link
                    href={`/stocks/${row.value.symbol}`}
                    onClick={() => setOpen(false)}
                  >
                    <strong>{row.value.title}</strong>
                  </Link>
                  <p>{row.value.body}</p>
                  {!row.value.read && (
                    <button
                      className="text-button"
                      onClick={async () => {
                        const r = await fetch(
                          `/api/service/notifications/${row.key}/read`,
                          { method: "POST" },
                        );
                        if (r.ok) void q.refetch();
                      }}
                    >
                      Mark read
                    </button>
                  )}
                </div>
              ),
            )
          ) : (
            <p>You’re all caught up.</p>
          )}
        </div>
      )}
    </div>
  );
}
