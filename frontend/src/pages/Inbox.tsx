import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";

export function Inbox() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: api.notifications,
  });

  const markRead = useMutation({
    mutationFn: (id: number) => api.markRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <div className="container" style={{ maxWidth: 760 }}>
      <h1>Inbox</h1>
      <p className="subtitle">Alerts delivered in-app.</p>

      {isLoading && <div className="empty">Loading…</div>}
      {data && data.length === 0 && (
        <div className="empty">
          Nothing yet. Create a rule on the <Link to="/alerts">Alerts</Link> page.
        </div>
      )}

      <div className="stack">
        {(data ?? []).map((n) => (
          <div
            key={n.id}
            className="card"
            style={{ borderLeft: n.read_at ? undefined : "3px solid var(--accent)" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <strong>{n.title}</strong>
              <span className="muted" style={{ whiteSpace: "nowrap" }}>
                {new Date(n.created_at).toLocaleString("en-IN", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                fontFamily: "inherit",
                margin: "10px 0 0",
                color: "var(--text-dim)",
                fontSize: 14,
              }}
            >
              {n.body}
            </pre>
            {!n.read_at && (
              <button
                className="btn secondary small"
                style={{ marginTop: 10 }}
                onClick={() => markRead.mutate(n.id)}
              >
                Mark read
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
