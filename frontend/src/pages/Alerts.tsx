import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import type { ChannelName, ServerConfig, User } from "../lib/types";

const RULE_TYPES = [
  { key: "LAST_DAY", label: "Last day to apply" },
  { key: "OPEN_DAY", label: "Opens for subscription" },
  { key: "ALLOTMENT_DAY", label: "Allotment day" },
  { key: "LISTING_DAY", label: "Listing day" },
  { key: "GMP_ABOVE", label: "GMP above (%)" },
  { key: "SUBSCRIPTION_ABOVE", label: "Subscription above (x)" },
];

const CHANNEL_LABELS: Record<ChannelName, string> = {
  INAPP: "In-app",
  EMAIL: "Email",
  TELEGRAM: "Telegram",
  WEBPUSH: "Browser push",
};

const NEEDS_THRESHOLD = new Set(["GMP_ABOVE", "SUBSCRIPTION_ABOVE"]);

/** Decode a base64url VAPID key into the ArrayBuffer `pushManager.subscribe` wants. */
function urlBase64ToBuffer(base64: string): ArrayBuffer {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  const buffer = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i += 1) view[i] = raw.charCodeAt(i);
  return buffer;
}

export function Alerts({ user, config }: { user: User; config: ServerConfig | undefined }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const channels = useQuery({ queryKey: ["channels"], queryFn: api.channels });
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["channels"] });
    queryClient.invalidateQueries({ queryKey: ["rules"] });
  };

  // --- rule form state ---
  const [ruleType, setRuleType] = useState("LAST_DAY");
  const [threshold, setThreshold] = useState("");
  const [selected, setSelected] = useState<ChannelName[]>(["INAPP"]);
  const [hours, setHours] = useState("10,15");
  const [watchlistOnly, setWatchlistOnly] = useState(false);

  const createRule = useMutation({
    mutationFn: () =>
      api.createRule({
        rule_type: ruleType,
        channels: selected,
        fire_hours_ist: hours
          .split(",")
          .map((h) => parseInt(h.trim(), 10))
          .filter((h) => !Number.isNaN(h)),
        threshold: NEEDS_THRESHOLD.has(ruleType) ? parseFloat(threshold) : null,
        watchlist_only: watchlistOnly,
      }),
    onSuccess: () => {
      setMessage({ kind: "ok", text: "Alert rule created." });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const addChannel = useMutation({
    mutationFn: (channel: ChannelName) => api.addChannel(channel, channel === "EMAIL" ? user.email : ""),
    onSuccess: () => refresh(),
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const testChannel = useMutation({
    mutationFn: (id: number) => api.testChannel(id),
    onSuccess: () => setMessage({ kind: "ok", text: "Test message sent." }),
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const enablePush = useMutation({
    mutationFn: async () => {
      if (!config?.vapid_public_key) throw new Error("Web push is not configured on the server.");
      if (!("serviceWorker" in navigator)) throw new Error("This browser has no service worker support.");

      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Notification permission was denied.");

      const registration = await navigator.serviceWorker.register("/sw.js");
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToBuffer(config.vapid_public_key),
      });
      return api.addChannel("WEBPUSH", JSON.stringify(subscription));
    },
    onSuccess: () => {
      setMessage({ kind: "ok", text: "Browser push enabled." });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const linkTelegram = useMutation({
    mutationFn: api.telegramLinkCode,
    onSuccess: (data) => {
      if (data.deep_link) window.open(data.deep_link, "_blank", "noopener");
      setMessage({
        kind: "ok",
        text: `Send "${data.command}" to the bot, then press "Check Telegram link".`,
      });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const available = (Object.keys(CHANNEL_LABELS) as ChannelName[]).filter(
    (c) => config?.channels?.[c],
  );
  const registered = new Set((channels.data ?? []).map((c) => c.channel));

  return (
    <div className="container">
      <h1>Alerts</h1>
      <p className="subtitle">
        Get told before an IPO window closes — the reminder this whole app exists for.
      </p>

      {message && <div className={message.kind === "ok" ? "success" : "error"}>{message.text}</div>}

      {/* ---------------- Channels ---------------- */}
      <div className="section">
        <div className="card">
          <h2>Delivery channels</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Channels the server has credentials for. Send a test before relying on one.
          </p>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Destination</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(channels.data ?? []).map((c) => (
                  <tr key={c.id}>
                    <td>{CHANNEL_LABELS[c.channel]}</td>
                    <td className="muted">{c.destination || "—"}</td>
                    <td>{c.is_active ? "Verified" : "Pending"}</td>
                    <td>
                      <button
                        className="btn secondary small"
                        disabled={!c.is_active || testChannel.isPending}
                        onClick={() => testChannel.mutate(c.id)}
                      >
                        Test
                      </button>{" "}
                      <button
                        className="btn danger small"
                        onClick={() =>
                          api.deleteChannel(c.id).then(refresh)
                        }
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
                {(channels.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No channels yet. Add one below.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="pill-list" style={{ marginTop: 16 }}>
            {available.includes("INAPP") && !registered.has("INAPP") && (
              <button className="btn secondary small" onClick={() => addChannel.mutate("INAPP")}>
                + In-app
              </button>
            )}
            {available.includes("EMAIL") && !registered.has("EMAIL") && (
              <button className="btn secondary small" onClick={() => addChannel.mutate("EMAIL")}>
                + Email ({user.email})
              </button>
            )}
            {available.includes("TELEGRAM") && (
              <>
                <button
                  className="btn secondary small"
                  onClick={() => linkTelegram.mutate()}
                  disabled={linkTelegram.isPending}
                >
                  + Link Telegram
                </button>
                <button
                  className="btn secondary small"
                  onClick={() => api.telegramPoll().then(refresh)}
                >
                  Check Telegram link
                </button>
              </>
            )}
            {available.includes("WEBPUSH") && !registered.has("WEBPUSH") && (
              <button
                className="btn secondary small"
                onClick={() => enablePush.mutate()}
                disabled={enablePush.isPending}
              >
                + Browser push
              </button>
            )}
          </div>

          {available.length <= 1 && (
            <p className="muted" style={{ marginTop: 12 }}>
              Only in-app delivery is available. Set <code>RESEND_API_KEY</code>,{" "}
              <code>TELEGRAM_BOT_TOKEN</code> or the VAPID keys on the server to enable the rest.
            </p>
          )}
        </div>
      </div>

      {/* ---------------- Rules ---------------- */}
      <div className="section">
        <div className="card">
          <h2>Create an alert rule</h2>

          <div className="row">
            <div className="field" style={{ flex: "1 1 220px" }}>
              <label htmlFor="rule-type">Alert me about</label>
              <select id="rule-type" value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
                {RULE_TYPES.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>

            {NEEDS_THRESHOLD.has(ruleType) && (
              <div className="field" style={{ flex: "0 1 140px" }}>
                <label htmlFor="threshold">Threshold</label>
                <input
                  id="threshold"
                  type="number"
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                  placeholder={ruleType === "GMP_ABOVE" ? "20" : "10"}
                />
              </div>
            )}

            {!NEEDS_THRESHOLD.has(ruleType) && (
              <div className="field" style={{ flex: "0 1 180px" }}>
                <label htmlFor="hours">Fire at (IST hours)</label>
                <input
                  id="hours"
                  type="text"
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                  placeholder="10,15"
                />
              </div>
            )}
          </div>

          <div className="field">
            <label>Deliver to</label>
            <div className="pill-list">
              {available.map((c) => (
                <button
                  key={c}
                  className={`chip${selected.includes(c) ? " active" : ""}`}
                  onClick={() =>
                    setSelected((prev) =>
                      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c],
                    )
                  }
                >
                  {CHANNEL_LABELS[c]}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={watchlistOnly}
                onChange={(e) => setWatchlistOnly(e.target.checked)}
              />
              Only for IPOs on my watchlist
            </label>
          </div>

          <button
            className="btn"
            onClick={() => createRule.mutate()}
            disabled={selected.length === 0 || createRule.isPending}
          >
            Create rule
          </button>
          {ruleType === "LAST_DAY" && (
            <p className="muted" style={{ marginTop: 10 }}>
              Applications usually close around 5:00 PM IST, so last-day alerts are never sent
              after 17:00.
            </p>
          )}
        </div>
      </div>

      {/* ---------------- Existing rules ---------------- */}
      <div className="card">
        <h2>Your rules</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Scope</th>
                <th>Channels</th>
                <th>When</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(rules.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{RULE_TYPES.find((t) => t.key === r.rule_type)?.label ?? r.rule_type}</td>
                  <td className="muted">
                    {r.ipo_id
                      ? "Single IPO"
                      : r.watchlist_only
                        ? "Watchlist only"
                        : "All IPOs"}
                  </td>
                  <td className="muted">{r.channels.join(", ")}</td>
                  <td className="muted">
                    {r.threshold !== null
                      ? `≥ ${r.threshold}`
                      : r.fire_hours_ist.map((h) => `${h}:00`).join(", ")}
                  </td>
                  <td>
                    <button
                      className="btn danger small"
                      onClick={() => api.deleteRule(r.id).then(refresh)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {(rules.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No rules yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
