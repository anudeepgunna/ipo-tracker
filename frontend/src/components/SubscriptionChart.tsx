import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SubscriptionPoint } from "../lib/types";

// Category order and colours are fixed so a series keeps its colour across IPOs.
const SERIES = [
  { key: "TOTAL", label: "Total", color: "#2563eb" },
  { key: "QIB", label: "QIB", color: "#16a34a" },
  { key: "NII", label: "NII", color: "#d97706" },
  { key: "RETAIL", label: "Retail", color: "#9333ea" },
  { key: "EMPLOYEE", label: "Employee", color: "#0891b2" },
];

/**
 * Subscription over time.
 *
 * The curve matters more than the current figure: most of an IPO's demand
 * arrives on the final day, so the slope is what tells you whether a book is
 * building or stalling.
 */
export function SubscriptionChart({ history }: { history: SubscriptionPoint[] }) {
  if (history.length === 0) {
    return <p className="muted">No subscription data recorded yet.</p>;
  }

  // Pivot [{captured_at, category, times}] into one row per timestamp.
  const byTime = new Map<string, Record<string, number | string>>();
  for (const point of history) {
    const stamp = point.captured_at;
    if (!byTime.has(stamp)) {
      byTime.set(stamp, {
        t: new Date(stamp).toLocaleString("en-IN", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }),
      });
    }
    if (point.times_subscribed !== null) {
      byTime.get(stamp)![point.category] = point.times_subscribed;
    }
  }

  const data = [...byTime.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, row]) => row);

  const present = SERIES.filter((s) => data.some((row) => row[s.key] !== undefined));

  // A single reading has no trend to draw; a table communicates it better.
  if (data.length < 2) {
    return (
      <div>
        <p className="muted" style={{ marginTop: 0 }}>
          Only one reading so far — the trend appears once the poller has run again.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th className="num">Times subscribed</th>
              </tr>
            </thead>
            <tbody>
              {present.map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td>
                  <td className="num">{Number(data[0][s.key]).toFixed(2)}x</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="t" tick={{ fontSize: 11, fill: "var(--text-dim)" }} />
        <YAxis
          tick={{ fontSize: 11, fill: "var(--text-dim)" }}
          tickFormatter={(v) => `${v}x`}
        />
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            color: "var(--text)",
            fontSize: 13,
          }}
          formatter={(value: number, name: string) => [`${value.toFixed(2)}x`, name]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {present.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={s.key === "TOTAL" ? 2.5 : 1.5}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
