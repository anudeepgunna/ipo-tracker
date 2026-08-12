import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";
import type { ServerConfig } from "../lib/types";

const GOOGLE_MARK = (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path
      fill="#EA4335"
      d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
    />
    <path
      fill="#4285F4"
      d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
    />
    <path
      fill="#FBBC05"
      d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
    />
    <path
      fill="#34A853"
      d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
    />
  </svg>
);

export function Login({ config }: { config?: ServerConfig }) {
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [devLink, setDevLink] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  // The Google callback bounces back here with ?error=... when consent fails.
  const [failure, setFailure] = useState<string | null>(params.get("error"));

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
        {config?.google_sign_in
          ? "Continue with Google, or get a single-use link by email."
          : "We'll email you a single-use link — no password to remember."}
      </p>

      <div className="card">
        {config?.google_sign_in && (
          <>
            <button
              className="google-btn"
              onClick={() => {
                // Full page navigation, not fetch: the OAuth consent screen has
                // to run top-level in the browser, and the callback needs to set
                // a cookie on the API origin.
                window.location.href = `${config.api_base_url}/api/auth/google/start`;
              }}
            >
              {GOOGLE_MARK}
              Continue with Google
            </button>
            <div className="divider">or</div>
          </>
        )}

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
              <strong>Could not sign you in.</strong>
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
          <a href="#/login">Request a new link</a>
        </>
      ) : (
        "Signing you in…"
      )}
    </div>
  );
}
