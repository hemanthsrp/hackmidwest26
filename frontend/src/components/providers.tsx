"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "next-auth/react";
import { useState } from "react";
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AccountQueries>{children}</AccountQueries>
    </SessionProvider>
  );
}
function AccountQueries({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  return (
    <ScopedQueries key={session?.user?.id || status}>{children}</ScopedQueries>
  );
}
function ScopedQueries({ children }: { children: React.ReactNode }) {
  const [query] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, staleTime: 60000 } },
      }),
  );
  return <QueryClientProvider client={query}>{children}</QueryClientProvider>;
}
