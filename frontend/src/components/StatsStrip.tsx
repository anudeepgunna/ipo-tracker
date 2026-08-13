import { useCountUp } from "../lib/motion";
import type { Ipo } from "../lib/types";

function Stat({
  value,
  label,
  tone,
  suffix = "",
  decimals = 0,
}: {
  value: number;
  label: string;
  tone?: "warn" | "good";
  suffix?: string;
  decimals?: number;
}) {
  const shown = useCountUp(value) ?? 0;
  return (
    <div className={`stat-tile${tone ? ` ${tone}` : ""}`}>
      <div className="stat-tile-value">
        {shown.toFixed(decimals)}
        {suffix}
      </div>
      <div className="stat-tile-label">{label}</div>
    </div>
  );
}

/**
 * The at-a-glance state of the market, above the grid.
 *
 * "Closing today" leads because it is the only number here that expires — every
 * other figure will still be true tomorrow.
 */
export function StatsStrip({ ipos }: { ipos: Ipo[] }) {
  const open = ipos.filter((i) => i.status === "OPEN");
  const closingToday = open.filter((i) => i.is_last_day);
  const upcoming = ipos.filter((i) => i.status === "UPCOMING");

  const subscribed = open
    .map((i) => i.subscription?.TOTAL)
    .filter((v): v is number => v != null);
  const hottest = subscribed.length ? Math.max(...subscribed) : 0;

  return (
    <div className="stats-strip">
      <Stat value={closingToday.length} label="Closing today" tone={closingToday.length ? "warn" : undefined} />
      <Stat value={open.length} label="Open now" tone="good" />
      <Stat value={upcoming.length} label="Opening soon" />
      <Stat value={hottest} label="Peak subscription" suffix="x" decimals={1} />
    </div>
  );
}
