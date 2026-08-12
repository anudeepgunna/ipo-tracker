import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";

export function Login() {
  const [email, setEmail] = useState("");
  const [devLink, setDevLink] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const request = useMutation({
    mutationFn: () => api.requestLink(email),
    onSuccess: (data) => {
      // The endpoint returns HTTP 200 even when delivery fails, so success here
      // means "the request was accepted", not "the mail was sent". Reporting
      // "check your inbox" on `sent: false` sends people to wait for an email
      // that will never arrive.
      setDevLink(data.dev_link ?? null);
      if (data.sent || data.dev_link) {
        setSent(true);
        setFailure(null);
      } else {
        setSent(false);
        setFailure(data.error ?? "The email could not be sent.");
      }
    },
    onError: (e: Error) => {
      setSent(false);
      setFailure(e.message);
    },
  });

  return (
    <div className="container" style={{ maxWidth: 460 }}>
      <h1>Sign in</h1>
      <p className="subtitle">
        We'll email you a single-use link — no password to remember.
      </p>

      <div className="card">
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            onKeyDown={(e) => e.key === "Enter" && email && request.mutate()}
          />
        </div>
        <button className="btn" onClick={() => request.mutate()} disabled={!email || request.isPending}>
          {request.isPending ? "Sending…" : "Send sign-in link"}
        </button>

        {sent && !devLink && (
          <p className="success">Check your inbox for the sign-in link.</p>
        )}
        {devLink && (
          <p className="success" style={{ wordBreak: "break-all" }}>
            Email isn't configured, so here's your link:{" "}
            <a href={devLink}>{devLink}</a>
          </p>
        )}
        {failure && (
          <div className="error">
            <p style={{ margin: "8px 0 4px" }}>
              <strong>The sign-in email could not be sent.</strong>
            </p>
            <p style={{ margin: 0 }}>{failure}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function Verify({ onSignedIn }: { onSignedIn: () => void }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const token = params.get("token");

  useEffect(() => {
    if (!token) {
      setError("This link is missing its token.");
      return;
    }
    api
      .verify(token)
      .then(() => {
        onSignedIn();
        navigate("/alerts", { replace: true });
      })
      .catch((e: Error) => setError(e.message));
  }, [token, navigate, onSignedIn]);

  return (
    <div className="container empty">
      {error ? (
        <>
          <p>{error}</p>
          <a href="/login">Request a new link</a>
        </>
      ) : (
        "Signing you in…"
      )}
    </div>
  );
}
