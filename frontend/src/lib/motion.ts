import { useEffect, useRef, useState } from "react";

/**
 * Whether the viewer has asked for reduced motion.
 *
 * Animation here is decoration, so it must be genuinely optional. Vestibular
 * disorders make large or continuous movement physically unpleasant, and this
 * app is something people open under time pressure on a closing day — the worst
 * moment to fight the interface. Every animated component degrades to its final
 * state instantly when this is true.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

/** Ease-out cubic: fast start, gentle settle. Reads as "arriving", not "sliding". */
const easeOut = (t: number) => 1 - (1 - t) ** 3;

/**
 * Counts from 0 to `value` on mount, and tweens between later values.
 *
 * Driven by requestAnimationFrame rather than a CSS transition because the
 * number itself has to change, not just its position.
 */
export function useCountUp(value: number | null, durationMs = 900): number | null {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState<number | null>(reduced ? value : 0);
  const fromRef = useRef(0);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (value === null) {
      setDisplay(null);
      return;
    }
    if (reduced) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }

    const from = fromRef.current;
    const start = performance.now();

    const tick = (now: number) => {
      const progress = Math.min((now - start) / durationMs, 1);
      setDisplay(from + (value - from) * easeOut(progress));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = value;
      }
    };

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      // Remember where we stopped, so an interrupted tween resumes from there
      // rather than snapping back to zero.
      fromRef.current = value;
    };
  }, [value, durationMs, reduced]);

  return display;
}

export interface Countdown {
  expired: boolean;
  hours: number;
  minutes: number;
  seconds: number;
}

/**
 * Time left until the IST application cutoff, but only on the closing day.
 *
 * Returns null otherwise, so the countdown appears exactly when it carries
 * information and never as permanent chrome.
 */
export function useCutoffCountdown(
  closeDate: string | null | undefined,
  cutoffHourIst = 17,
): Countdown | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!closeDate) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [closeDate]);

  if (!closeDate) return null;

  const [y, m, d] = closeDate.split("-").map(Number);
  if (!y || !m || !d) return null;

  // IST is UTC+5:30 year-round with no daylight saving, so a fixed offset is exact.
  const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
  const cutoffUtcMs = Date.UTC(y, m - 1, d, cutoffHourIst, 0, 0) - IST_OFFSET_MS;

  const istNow = new Date(now + IST_OFFSET_MS);
  const isCloseDay =
    istNow.getUTCFullYear() === y && istNow.getUTCMonth() === m - 1 && istNow.getUTCDate() === d;
  if (!isCloseDay) return null;

  const remaining = cutoffUtcMs - now;
  if (remaining <= 0) return { expired: true, hours: 0, minutes: 0, seconds: 0 };

  return {
    expired: false,
    hours: Math.floor(remaining / 3_600_000),
    minutes: Math.floor((remaining % 3_600_000) / 60_000),
    seconds: Math.floor((remaining % 60_000) / 1000),
  };
}
