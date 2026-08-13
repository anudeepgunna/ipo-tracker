import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";

import { BackToTop, ScrollProgress } from "./components/ScrollChrome";
import { ThemeToggle } from "./components/ThemeToggle";
import { api } from "./lib/api";
import { useScrolledPast } from "./lib/motion";
import { takePending } from "./lib/pendingReminder";
import { Alerts } from "./pages/Alerts";
import { Dashboard } from "./pages/Dashboard";
import { Inbox } from "./pages/Inbox";
import { IpoDetailPage } from "./pages/IpoDetailPage";
import { Login, Verify } from "./pages/Login";

function Nav({ signedIn, onSignOut }: { signedIn: boolean; onSignOut: () => void }) {
  const { pathname } = useLocation();
  const isActive = (path: string) => (pathname === path ? "active" : "");
  const condensed = useScrolledPast(60);

  return (
    <nav className={`nav${condensed ? " condensed" : ""}`}>
      <div className="nav-inner">
        <Link to="/" className="brand">
          IPO Tracker
        </Link>
        <div className="nav-links">
          <ThemeToggle />
          <Link to="/" className={isActive("/")}>
            Dashboard
          </Link>
          {signedIn ? (
            <>
              <Link to="/inbox" className={isActive("/inbox")}>
                Inbox
              </Link>
              <Link to="/alerts" className={isActive("/alerts")}>
                Alerts
              </Link>
              <button className="btn secondary small" onClick={onSignOut}>
                Sign out
              </button>
            </>
          ) : (
            <Link to="/login" className={isActive("/login")}>
              Sign in
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}

export default function App() {
  const queryClient = useQueryClient();

  // A 401 here is the normal signed-out state, not an error worth retrying.
  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me().catch(() => null),
    retry: false,
  });

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });

  const signOut = async () => {
    await api.logout();
    queryClient.clear();
  };

  // A visitor who picked reminder options and then signed in should come back to
  // those reminders already created — not to a dashboard that forgot, forcing
  // them to repeat the choice they just made.
  const [replayToast, setReplayToast] = useState<string | null>(null);
  useEffect(() => {
    if (!user) return;
    const pending = takePending();
    if (!pending) return;

    (async () => {
      try {
        for (const cadence of pending.cadences) {
          await api.createRule({
            rule_type: cadence,
            ipo_id: pending.ipoId,
            channels: ["INAPP", "EMAIL"],
            fire_hours_ist: cadence === "LAST_DAY" ? [10, 15] : [10],
          });
        }
        queryClient.invalidateQueries({ queryKey: ["rules"] });
        setReplayToast(`Reminder set for ${pending.ipoName}`);
      } catch {
        setReplayToast("Signed in, but the reminder could not be saved. Please set it again.");
      }
    })();
  }, [user?.id]);

  useEffect(() => {
    if (!replayToast) return;
    const t = setTimeout(() => setReplayToast(null), 3200);
    return () => clearTimeout(t);
  }, [replayToast]);

  return (
    <>
      <ScrollProgress />
      <Nav signedIn={!!user} onSignOut={signOut} />
      {replayToast && <div className="toast">{replayToast}</div>}
      <Routes>
        <Route path="/" element={<Dashboard user={user ?? null} config={config} />} />
        <Route path="/ipo/:symbol" element={<IpoDetailPage />} />
        <Route path="/login" element={<Login config={config} />} />
        <Route
          path="/auth/verify"
          element={<Verify onSignedIn={() => queryClient.invalidateQueries()} />}
        />
        <Route
          path="/alerts"
          element={user ? <Alerts user={user} config={config} /> : <Login config={config} />}
        />
        <Route path="/inbox" element={user ? <Inbox /> : <Login config={config} />} />
        <Route path="*" element={<div className="container empty">Page not found.</div>} />
      </Routes>
      <BackToTop />
    </>
  );
}
