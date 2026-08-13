import { useCutoffCountdown } from "../lib/motion";

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Live time-to-cutoff on a closing day.
 *
 * The single most decision-relevant number on the page when it appears: retail
 * UPI mandates must be approved before roughly 17:00 IST, so "closes today" and
 * "closes in 26 minutes" call for very different behaviour. It renders nothing
 * on any other day rather than sitting there as permanent chrome.
 */
export function Countdown({ closeDate, compact = false }: { closeDate: string | null; compact?: boolean }) {
  const left = useCutoffCountdown(closeDate);
  if (!left) return null;

  if (left.expired) {
    return (
      <div className={`countdown expired${compact ? " compact" : ""}`}>
        <span className="countdown-label">Applications closed for today</span>
      </div>
    );
  }

  // Under an hour is the point where this stops being informational and starts
  // being urgent, so it changes colour and starts pulsing.
  const urgent = left.hours < 1;

  return (
    <div className={`countdown${urgent ? " urgent" : ""}${compact ? " compact" : ""}`}>
      <span className="countdown-label">Closes in</span>
      <span className="countdown-time">
        {left.hours > 0 && (
          <>
            <b>{pad(left.hours)}</b>
            <i>h</i>
          </>
        )}
        <b>{pad(left.minutes)}</b>
        <i>m</i>
        <b>{pad(left.seconds)}</b>
        <i>s</i>
      </span>
    </div>
  );
}
