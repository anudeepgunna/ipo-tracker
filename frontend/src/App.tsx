import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useLocation } from "react-router-dom";

import { api } from "./lib/api";
import { Alerts } from "./pages/Alerts";
import { Dashboard } from "./pages/Dashboard";
import { Inbox } from "./pages/Inbox";
import { IpoDetailPage } from "./pages/IpoDetailPage";
import { Login, Verify } from "./pages/Login";

function Nav({ signedIn, onSignOut }: { signedIn: boolean; onSignOut: () => void }) {
  const { pathname } = useLocation();
  const isActive = (path: string) => (pathname === path ? "active" : "");

  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link to="/" className="brand">
          IPO Tracker
        </Link>
        <div className="nav-links">
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

  return (
    <>
      <Nav signedIn={!!user} onSignOut={signOut} />
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
    </>
  );
}
