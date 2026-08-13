import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { IpoCard } from "../components/IpoCard";
import { ReminderDialog } from "../components/ReminderDialog";
import { SkeletonGrid } from "../components/Skeleton";
import { StatsStrip } from "../components/StatsStrip";
import { api } from "../lib/api";
import { useScrollReveal } from "../lib/motion";
import type { Ipo, ServerConfig, User } from "../lib/types";

const FILTERS = [
  { key: "", label: "Everything" },
  { key: "OPEN", label: "Open now" },
  { key: "UPCOMING", label: "Opening soon" },
  { key: "CLOSED", label: "Closed" },
  { key: "LISTED", label: "Listed" },
];

const SORTS = [
  { key: "closing", label: "Closing soonest" },
  { key: "subscription", label: "Most subscribed" },
  { key: "score", label: "Best outlook" },
  { key: "investment", label: "Lowest investment" },
  { key: "name", label: "Name (A–Z)" },
];

/**
 * Sections shown when no single status is selected.
 *
 * Ordered by urgency rather than lifecycle: what you can still act on comes
 * first, and what has already happened sinks to the bottom.
 */
const SECTIONS = [
  {
    key: "closing",
    title: "Closing today",
    hint: "Applications cut off around 5:00 PM IST",
    match: (i: Ipo) => i.status === "OPEN" && i.is_last_day,
  },
  {
    key: "open",
    title: "Open now",
    hint: "Accepting applications",
    match: (i: Ipo) => i.status === "OPEN" && !i.is_last_day,
  },
  {
    key: "upcoming",
    title: "Opening soon",
    hint: "Set a reminder before the window opens",
    match: (i: Ipo) => i.status === "UPCOMING",
  },
  {
    key: "closed",
    title: "Closed — awaiting listing",
    hint: "Subscription final, allotment pending",
    match: (i: Ipo) => i.status === "CLOSED",
  },
  {
    key: "listed",
    title: "Recently listed",
    hint: null,
    match: (i: Ipo) => i.status === "LISTED",
  },
];

function sortIpos(list: Ipo[], by: string): Ipo[] {
  const out = [...list];
  switch (by) {
    case "subscription":
      return out.sort((a, b) => (b.subscription?.TOTAL ?? -1) - (a.subscription?.TOTAL ?? -1));
    case "score":
      return out.sort((a, b) => (b.score?.score ?? -1) - (a.score?.score ?? -1));
    case "investment":
      return out.sort((a, b) => (a.min_investment ?? Infinity) - (b.min_investment ?? Infinity));
    case "name":
      return out.sort((a, b) => a.company_name.localeCompare(b.company_name));
    default:
      return out.sort((a, b) => (a.close_date ?? "9999").localeCompare(b.close_date ?? "9999"));
  }
}

/** A titled group of cards that fades in as it scrolls into view. */
function Section({
  title,
  hint,
  ipos,
  render,
}: {
  title: string;
  hint: string | null;
  ipos: Ipo[];
  render: (ipo: Ipo, index: number) => React.ReactNode;
}) {
  const { ref, shown } = useScrollReveal<HTMLElement>();
  if (ipos.length === 0) return null;

  return (
    <section ref={ref} className={`ipo-section${shown ? " in" : ""}`}>
      <div className="section-head">
        <h2>
          {title}
          <span className="section-count">{ipos.length}</span>
        </h2>
        {hint && <span className="muted section-hint">{hint}</span>}
      </div>
      <div className="grid">{ipos.map(render)}</div>
    </section>
  );
}

export function Dashboard({
  user,
  config,
}: {
  user: User | null;
  config: ServerConfig | undefined;
}) {
  // Defaults to everything, grouped by urgency — an upcoming IPO you can't yet
  // apply to is exactly the one worth setting a reminder for, so hiding it
  // behind a filter defeats the point of the app.
  const [status, setStatus] = useState("");
  const [board, setBoard] = useState("");
  const [sort, setSort] = useState("closing");
  const [watchOnly, setWatchOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [remindFor, setRemindFor] = useState<Ipo | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules, enabled: !!user });

  const { data, isLoading, error } = useQuery({
    queryKey: ["ipos", status, board, watchOnly],
    queryFn: () =>
      api.listIpos({
        status: status || undefined,
        board: board || undefined,
        watchlist: watchOnly || undefined,
      }),
    refetchOnWindowFocus: true,
    // A free Render instance sleeps when idle and can take ~50s to wake, often
    // 502-ing on the way up. Retry so the first visit of the day recovers alone.
    retry: 4,
    retryDelay: (attempt) => Math.min(2000 * 2 ** attempt, 15000),
  });

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
    onSuccess: (_r, ipo) => {
      queryClient.invalidateQueries({ queryKey: ["ipos"] });
      setToast(ipo.watchlisted ? "Removed from watchlist" : "Added to watchlist");
    },
  });

  const rulesByIpo = new Map<number, number>();
  for (const r of rules.data ?? []) {
    if (r.ipo_id != null && r.active) {
      rulesByIpo.set(r.ipo_id, (rulesByIpo.get(r.ipo_id) ?? 0) + 1);
    }
  }

  const term = search.trim().toLowerCase();
  const visible = sortIpos(
    (data ?? []).filter(
      (i) =>
        !term ||
        i.company_name.toLowerCase().includes(term) ||
        i.symbol.toLowerCase().includes(term),
    ),
    sort,
  );

  const lastDay = visible.filter((i) => i.is_last_day);
  // An explicit filter or a search already states the intent, so grouping there
  // would just add headings to a list the user has already narrowed.
  const grouped = status === "" && !term;

  const card = (ipo: Ipo, index: number) => (
    <IpoCard
      key={ipo.id}
      index={index}
      ipo={ipo}
      signedIn={!!user}
      reminderCount={rulesByIpo.get(ipo.id) ?? 0}
      onToggleWatch={(i) => toggleWatch.mutate(i)}
      onRemind={(i) => setRemindFor(i)}
    />
  );

  return (
    <div className="container">
      <h1>IPO Tracker</h1>
      <p className="subtitle">
        Live subscription from NSE, grey market premium and listing estimates for Indian IPOs.
      </p>

      {lastDay.length > 0 && (
        <div className="alert-banner">
          ⚠️ Closing today: {lastDay.map((i) => i.company_name).join(", ")} — applications
          typically cut off at 5:00 PM IST.
        </div>
      )}

      {data && data.length > 0 && <StatsStrip ipos={data} />}

      <div className="toolbar">
        <input
          type="text"
          className="search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by company or symbol…"
          aria-label="Search IPOs"
        />
        <select
          className="sort-select"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          aria-label="Sort IPOs"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

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
        <span className="filter-sep" />
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
        <>
          {slow && (
            <div className="waking">
              <span className="waking-spinner" />
              <div>
                <strong>Waking the server…</strong>
                <p className="muted" style={{ margin: "2px 0 0" }}>
                  The free instance sleeps when idle, so the first load of the day can take
                  up to a minute. Later loads are instant.
                </p>
              </div>
            </div>
          )}
          <SkeletonGrid count={6} />
        </>
      )}

      {error && (
        <div className="empty">
          <p style={{ margin: 0 }}>Could not load IPOs.</p>
          <p className="muted" style={{ marginTop: 6 }}>
            {(error as Error).message}
          </p>
          <button
            className="btn secondary small"
            style={{ marginTop: 12 }}
            onClick={() => queryClient.invalidateQueries({ queryKey: ["ipos"] })}
          >
            Retry
          </button>
        </div>
      )}

      {data && visible.length === 0 && (
        <div className="empty">
          {term ? (
            <>
              Nothing matches “{search}”.{" "}
              <button className="btn secondary small" onClick={() => setSearch("")}>
                Clear search
              </button>
            </>
          ) : (
            "No IPOs match this filter."
          )}
        </div>
      )}

      {visible.length > 0 &&
        (grouped ? (
          SECTIONS.map((s) => (
            <Section
              key={s.key}
              title={s.title}
              hint={s.hint}
              ipos={visible.filter(s.match)}
              render={card}
            />
          ))
        ) : (
          <div className="grid">{visible.map(card)}</div>
        ))}

      {remindFor && (
        <ReminderDialog
          ipo={remindFor}
          config={config}
          user={user}
          onClose={() => setRemindFor(null)}
          onDone={(m) => setToast(m)}
        />
      )}

      {toast && <div className="toast">{toast}</div>}

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
