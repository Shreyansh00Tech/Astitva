// Live updates use WebSockets locally (Docker / run-local.sh). Serverless hosts such as Vercel cannot keep
// a socket open, so there the app polls faster instead. NEXT_PUBLIC_REALTIME=poll|ws overrides the choice.
const mode = process.env.NEXT_PUBLIC_REALTIME || (process.env.NEXT_PUBLIC_VERCEL_ENV ? "poll" : "ws");

export const socketsEnabled = mode !== "poll";

/** Refresh interval: the normal one when WebSockets push changes, a shorter one when only polling. */
export const live = (withSocket: number, pollingOnly: number) => (socketsEnabled ? withSocket : pollingOnly);
