import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { IpoCard } from "../components/IpoCard";
import { api } from "../lib/api";
import type { Ipo, User } from "../lib/types";

const FILTERS = [
  { key: "OPEN", label: "Open now" },
  { key: "UPCOMING", label: "Upcoming" },
  { key: "CLOSED", label: "Closed" },
  { key: "", label: "All" },
];

export function Dashboard({ user }: { user: User | null }) {
  const [status, setStatus] = useState("OPEN");
  const [board, setBoard] = useState("");
  const [watchOnly, setWatchOnly] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["ipos", status, board, watchOnly],
    queryFn: () =>
      api.listIpos({
        status: status || undefined,
        board: board || undefined,
        watchlist: watchOnly || undefined,
      }),
    // The poller writes at most every 15 minutes; refetching on focus is enough.
    refetchOnWindowFocus: true,
    // A free Render instance sleeps when idle and can take ~50s to wake, often
    // 502-ing on the way up. Retry generously so the first visit of the day
    // recovers on its own instead of showing an error.
    retry: 4,
    retryDelay: (attempt) => Math.min(2000 * 2 ** attempt, 15000),
  });

  // Distinguish "slow" from "broken": without this, a cold start looks identical
  // to a failure for the better part of a minute.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!isLoading) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(timer);
  }, [isLoading]);

  const toggleWatch = useMutation({
    mutationFn: (ipo: Ipo) => (ipo.watchlisted ? api.removeWatch(ipo.id) : api.addWatch(ipo.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ipos"] }),
  });

  const lastDay = (data ?? []).filter((i) => i.is_last_day);

  return (
    <div className="container">
      <h1>IPO Tracker</h1>
      <p className="subtitle">
        Live subscription from NSE, grey market premium and listing estimates for Indian IPOs.
      </p>

      {lastDay.length > 0 && (
        <div className="alert-banner">
          ⚠️ Closing today:{" "}
          {lastDay.map((i) => i.company_name).join(", ")} — applications typically cut off at
          5:00 PM IST.
        </div>
      )}

      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip${status === f.key ? " active" : ""}`}
            onClick={() => setStatus(f.key)}
          >
            {f.label}
          </button>
        ))}
        <span style={{ width: 12 }} />
        {[
          { key: "", label: "All boards" },
          { key: "MAINBOARD", label: "Mainboard" },
          { key: "SME", label: "SME" },
        ].map((b) => (
          <button
            key={b.key}
            className={`chip${board === b.key ? " active" : ""}`}
            onClick={() => setBoard(b.key)}
          >
            {b.label}
          </button>
        ))}
        {user && (
          <button
            className={`chip${watchOnly ? " active" : ""}`}
            onClick={() => setWatchOnly((v) => !v)}
          >
            ★ Watchlist
          </button>
        )}
      </div>

      {isLoading && (
        <div className="empty">
          {slow ? (
            <>
              <p style={{ margin: 0 }}>Waking the server…</p>
              <p className="muted" style={{ marginTop: 6 }}>
                The free instance sleeps when idle, so the first load of the day can take
                up to a minute. Later loads are instant.
              </p>
            </>
          ) : (
            "Loading IPOs…"
          )}
        </div>
      )}
      {error && (
        <div className="empty">
          <p style={{ margin: 0 }}>Could not load IPOs.</p>
          <p className="muted" style={{ marginTop: 6 }}>{(error as Error).message}</p>
          <button
            className="btn secondary small"
            style={{ marginTop: 12 }}
            onClick={() => queryClient.invalidateQueries({ queryKey: ["ipos"] })}
          >
            Retry
          </button>
        </div>
      )}

      {data && data.length === 0 && (
        <div className="empty">
          No IPOs match this filter.
          {status === "OPEN" && " There may be none open right now — try Upcoming."}
        </div>
      )}

      {data && data.length > 0 && (
        <div className="grid">
          {data.map((ipo) => (
            <IpoCard
              key={ipo.id}
              ipo={ipo}
              signedIn={!!user}
              onToggleWatch={(i) => toggleWatch.mutate(i)}
            />
          ))}
        </div>
      )}

      <div className="disclaimer">
        <strong>Informational only — not investment advice.</strong> Subscription figures come
        from NSE and are published periodically, not in real time. Grey market premium (GMP) is
        an unofficial, unregulated and thinly traded indicator that is easily manipulated; it is
        not a forecast of the listing price. The listing outlook score is a transparent heuristic
        over these inputs, not a prediction. Always read the RHP before applying.
      </div>
    </div>
  );
}
