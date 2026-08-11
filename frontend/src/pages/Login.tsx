import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";

export function Login() {
  const [email, setEmail] = useState("");
  const [devLink, setDevLink] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const request = useMutation({
    mutationFn: () => api.requestLink(email),
    onSuccess: (data) => {
      setSent(true);
      // Without an email provider configured the server hands back the link so
      // local development isn't locked out.
      setDevLink(data.dev_link ?? null);
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
        {request.error && <p className="error">{(request.error as Error).message}</p>}
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
