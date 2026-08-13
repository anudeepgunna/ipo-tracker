import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { savePending } from "../lib/pendingReminder";
import type { ChannelName, Ipo, ServerConfig, User } from "../lib/types";

/** Cadences offered per IPO, ordered the way people actually think about them. */
export const CADENCES = [
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
  user,
  onClose,
  onDone,
}: {
  ipo: Ipo;
  config: ServerConfig | undefined;
  user: User | null;
  onClose: () => void;
  onDone?: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const signedIn = !!user;

  const [cadences, setCadences] = useState<string[]>(["LAST_DAY"]);
  const [channels, setChannels] = useState<ChannelName[]>(["INAPP"]);
  const [email, setEmail] = useState("");
  // Signed-out visitors choose cadences first and identify themselves second,
  // so the value is visible before anything is asked of them.
  const [step, setStep] = useState<"choose" | "identify">("choose");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);

  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules, enabled: signedIn });
  const userChannels = useQuery({
    queryKey: ["channels"],
    queryFn: api.channels,
    enabled: signedIn,
  });

  // Only offer channels the server can deliver on AND the user has verified —
  // a dead option just becomes a silent non-delivery later.
  const usable = (Object.keys(CHANNEL_LABELS) as ChannelName[]).filter(
    (c) =>
      config?.channels?.[c] &&
      (userChannels.data ?? []).some((x) => x.channel === c && x.is_active),
  );

  useEffect(() => {
    if (signedIn && usable.length && !usable.some((c) => channels.includes(c))) {
      setChannels([usable[0]]);
    }
  }, [signedIn, usable.join(","), channels.join(",")]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const existing = (rules.data ?? []).filter((r) => r.ipo_id === ipo.id);

  const toggle = <T,>(list: T[], value: T, set: (v: T[]) => void) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  // --- signed in: create rules directly ---
  const createRules = useMutation({
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
      onDone?.("Reminder set");
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  // --- signed out: create by email, confirm afterwards ---
  const subscribeByEmail = useMutation({
    mutationFn: () => api.subscribe({ email, ipo_id: ipo.id, cadences }),
    onSuccess: (data) => {
      if (!data.ok) {
        setError(data.error ?? "Could not save that reminder.");
        return;
      }
      setDevLink(data.dev_link ?? null);
      setDone(
        data.message ??
          (data.sent
            ? `Check ${email} to confirm — alerts start once you do.`
            : "Reminder saved."),
      );
      if (data.error) setError(data.error);
    },
    onError: (e: Error) => setError(e.message),
  });

  const removeRule = useMutation({
    mutationFn: (id: number) => api.deleteRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });

  const startGoogle = () => {
    // Persist the choices first: the page is about to navigate away entirely.
    savePending({ ipoId: ipo.id, ipoName: ipo.company_name, cadences });
    window.location.href = `${config?.api_base_url ?? ""}/api/auth/google/start`;
  };

  const closeLabel = new Date(ipo.close_date ?? "").toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });

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
            <h2 style={{ margin: 0 }}>{done ? "Reminder saved" : "Remind me"}</h2>
            <p className="muted" style={{ margin: "2px 0 0" }}>
              {ipo.company_name}
              {ipo.close_date && ` · closes ${closeLabel}`}
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {/* ---------- confirmation ---------- */}
        {done ? (
          <>
            <p style={{ marginTop: 0 }}>{done}</p>
            {devLink && (
              <p className="success" style={{ wordBreak: "break-all" }}>
                Email isn't configured here, so confirm directly:{" "}
                <a href={devLink}>{devLink}</a>
              </p>
            )}
            {error && <p className="error">{error}</p>}
            <div className="modal-actions">
              <button className="btn" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        ) : (
          <>
            {/* ---------- step 1: cadence ---------- */}
            {step === "choose" && (
              <>
                {signedIn && existing.length > 0 && (
                  <div className="field">
                    <label>Already set</label>
                    {existing.map((r) => (
                      <div key={r.id} className="rule-row">
                        <span>
                          {CADENCES.find((c) => c.key === r.rule_type)?.label ?? r.rule_type}
                          <span className="muted"> · {r.channels.join(", ")}</span>
                        </span>
                        <button
                          className="btn danger small"
                          onClick={() => removeRule.mutate(r.id)}
                        >
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
                        <span className="option-check">
                          {cadences.includes(c.key) ? "✓" : ""}
                        </span>
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

                {signedIn && (
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
                )}

                {error && <p className="error">{error}</p>}

                <div className="modal-actions">
                  <button className="btn secondary" onClick={onClose}>
                    Cancel
                  </button>
                  <button
                    className="btn"
                    disabled={
                      !cadences.length ||
                      (signedIn && (!channels.length || createRules.isPending))
                    }
                    onClick={() => (signedIn ? createRules.mutate() : setStep("identify"))}
                  >
                    {signedIn ? (createRules.isPending ? "Saving…" : "Set reminder") : "Continue"}
                  </button>
                </div>
              </>
            )}

            {/* ---------- step 2: who are you ---------- */}
            {step === "identify" && (
              <>
                <p className="muted" style={{ marginTop: 0 }}>
                  Where should we send{" "}
                  {cadences.length > 1 ? "these reminders" : "this reminder"}?
                </p>

                {config?.google_sign_in && (
                  <>
                    <button className="google-btn" onClick={startGoogle}>
                      Continue with Google
                    </button>
                    <div className="divider">or</div>
                  </>
                )}

                <div className="field">
                  <label htmlFor="reminder-email">Email</label>
                  <input
                    id="reminder-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoFocus
                    onKeyDown={(e) =>
                      e.key === "Enter" && email && subscribeByEmail.mutate()
                    }
                  />
                </div>

                <p className="muted" style={{ fontSize: 12 }}>
                  We'll send one email to confirm the address. No alerts go out until you
                  click it.
                </p>

                {error && <p className="error">{error}</p>}

                <div className="modal-actions">
                  <button className="btn secondary" onClick={() => setStep("choose")}>
                    Back
                  </button>
                  <button
                    className="btn"
                    disabled={!email || subscribeByEmail.isPending}
                    onClick={() => subscribeByEmail.mutate()}
                  >
                    {subscribeByEmail.isPending ? "Saving…" : "Set reminder"}
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {!done && (
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 14 }}>
            Applications usually close around 5:00 PM IST, so last-day reminders are never
            sent after 17:00.
          </p>
        )}
      </div>
    </div>
  );
}
