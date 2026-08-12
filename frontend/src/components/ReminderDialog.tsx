import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ChannelName, Ipo, ServerConfig } from "../lib/types";

/** The cadences offered per IPO, in the order a person actually thinks about them. */
const CADENCES = [
  {
    key: "LAST_DAY",
    label: "Only on the last day",
    detail: "Two nudges on the closing date, at 10:00 and 15:00 IST.",
  },
  {
    key: "DAY_BEFORE_CLOSE",
    label: "The day before it closes",
    detail: "One heads-up with a full day left to arrange funds.",
  },
  {
    key: "DAILY_UNTIL_CLOSE",
    label: "Every day until it closes",
    detail: "One reminder each morning for the whole window, escalating on the last day.",
  },
] as const;

const CHANNEL_LABELS: Record<ChannelName, string> = {
  INAPP: "In-app",
  EMAIL: "Email",
  TELEGRAM: "Telegram",
  WEBPUSH: "Browser push",
};

export function ReminderDialog({
  ipo,
  config,
  onClose,
}: {
  ipo: Ipo;
  config: ServerConfig | undefined;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [cadences, setCadences] = useState<string[]>(["LAST_DAY"]);
  const [channels, setChannels] = useState<ChannelName[]>(["INAPP"]);
  const [error, setError] = useState<string | null>(null);

  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const userChannels = useQuery({ queryKey: ["channels"], queryFn: api.channels });

  // Only offer channels the server can actually deliver on AND the user has set
  // up — offering a dead option just produces a silent failure later.
  const usable = (Object.keys(CHANNEL_LABELS) as ChannelName[]).filter(
    (c) => config?.channels?.[c] && (userChannels.data ?? []).some((x) => x.channel === c && x.is_active),
  );

  useEffect(() => {
    if (usable.length && !usable.some((c) => channels.includes(c))) {
      setChannels([usable[0]]);
    }
  }, [usable.join(","), channels.join(",")]);

  const existing = (rules.data ?? []).filter((r) => r.ipo_id === ipo.id);

  // Escape to dismiss — a modal that traps you is worse than no modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const create = useMutation({
    mutationFn: async () => {
      for (const cadence of cadences) {
        await api.createRule({
          rule_type: cadence,
          ipo_id: ipo.id,
          channels,
          fire_hours_ist: cadence === "LAST_DAY" ? [10, 15] : [10],
        });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });

  const toggle = <T,>(list: T[], value: T, set: (v: T[]) => void) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Remind me about ${ipo.company_name}`}
      >
        <div className="modal-head">
          <div>
            <h2 style={{ margin: 0 }}>Remind me</h2>
            <p className="muted" style={{ margin: "2px 0 0" }}>
              {ipo.company_name}
              {ipo.close_date && ` · closes ${new Date(ipo.close_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}`}
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {existing.length > 0 && (
          <div className="section" style={{ marginBottom: 20 }}>
            <label>Existing reminders</label>
            {existing.map((r) => (
              <div key={r.id} className="rule-row">
                <span>
                  {CADENCES.find((c) => c.key === r.rule_type)?.label ?? r.rule_type}
                  <span className="muted"> · {r.channels.join(", ")}</span>
                </span>
                <button className="btn danger small" onClick={() => remove.mutate(r.id)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="field">
          <label>When should I remind you?</label>
          <div className="option-list">
            {CADENCES.map((c) => (
              <button
                key={c.key}
                className={`option${cadences.includes(c.key) ? " selected" : ""}`}
                onClick={() => toggle(cadences, c.key, setCadences)}
              >
                <span className="option-check">{cadences.includes(c.key) ? "✓" : ""}</span>
                <span>
                  <strong>{c.label}</strong>
                  <span className="muted" style={{ display: "block", fontSize: 12 }}>
                    {c.detail}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>Send it where?</label>
          {usable.length > 0 ? (
            <div className="pill-list">
              {usable.map((c) => (
                <button
                  key={c}
                  className={`chip${channels.includes(c) ? " active" : ""}`}
                  onClick={() => toggle(channels, c, setChannels)}
                >
                  {CHANNEL_LABELS[c]}
                </button>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              No delivery channel set up yet. Add one on the Alerts page first.
            </p>
          )}
        </div>

        {error && <p className="error">{error}</p>}

        <div className="modal-actions">
          <button className="btn secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn"
            onClick={() => create.mutate()}
            disabled={!cadences.length || !channels.length || create.isPending}
          >
            {create.isPending ? "Saving…" : "Set reminder"}
          </button>
        </div>

        <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 14 }}>
          Applications usually close around 5:00 PM IST, so last-day reminders are never
          sent after 17:00.
        </p>
      </div>
    </div>
  );
}
