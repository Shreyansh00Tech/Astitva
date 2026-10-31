"use client";

import { useEffect, useRef } from "react";
import { Bot, Fingerprint, ScrollText, ShieldCheck } from "lucide-react";
import { Wordmark } from "@/components/logo";

const FEATURES: [any, string][] = [
  [Fingerprint, "Purpose-bound, short-lived access tokens"],
  [ShieldCheck, "Sensitive data always needs a human approver"],
  [Bot, "Gateway-enforced AI agent permissions"],
  [ScrollText, "SHA-256 hash-chained audit trail"],
];
const HEADLINE = "Every access decision, justified, time-bound and provable.".split(" ");

/**
 * Login hero. All motion is CSS transform/opacity (GPU-composited, no layout or paint per frame), so it stays
 * at the display's refresh rate. The pointer spotlight is moved with a single rAF-throttled transform.
 * Everything is switched off for prefers-reduced-motion.
 */
export function AuthVisual() {
  const root = useRef<HTMLDivElement>(null);
  const spot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current, s = spot.current;
    if (!el || !s || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0, x = 0, y = 0;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      x = e.clientX - r.left; y = e.clientY - r.top;
      if (!raf) raf = requestAnimationFrame(() => { s.style.transform = `translate3d(${x - 300}px, ${y - 300}px, 0)`; s.style.opacity = "1"; raf = 0; });
    };
    const leave = () => { s.style.opacity = "0"; };
    el.addEventListener("pointermove", move, { passive: true });
    el.addEventListener("pointerleave", leave);
    return () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); cancelAnimationFrame(raf); };
  }, []);

  return (
    <div ref={root} className="auth-hero relative hidden overflow-hidden bg-[#070910] text-white lg:block">
      <div className="absolute inset-0 opacity-[0.35]" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.06) 1px, transparent 1px)", backgroundSize: "40px 40px", maskImage: "radial-gradient(ellipse at 40% 50%, #000 40%, transparent 85%)" }} />
      <div className="auth-scan pointer-events-none absolute inset-x-0 top-0 h-40" />
      {/* soft glows drawn with gradients, not CSS blur filters, so moving them costs nothing per frame */}
      <div className="auth-orb-a absolute -left-72 top-[12%] h-[760px] w-[760px] rounded-full" style={{ background: "radial-gradient(circle, rgba(109,74,255,.28), rgba(109,74,255,.08) 40%, transparent 68%)" }} />
      <div className="auth-orb-b absolute -bottom-72 -right-32 h-[640px] w-[640px] rounded-full" style={{ background: "radial-gradient(circle, rgba(42,120,214,.24), rgba(42,120,214,.06) 40%, transparent 68%)" }} />
      <div ref={spot} className="pointer-events-none absolute left-0 top-0 h-[600px] w-[600px] rounded-full opacity-0 transition-opacity duration-500" style={{ background: "radial-gradient(circle, rgba(140,115,255,.16), transparent 60%)", willChange: "transform" }} />

      {/* Orbit emblem: identities circling a protected core */}
      <div className="auth-emblem pointer-events-none absolute right-[-170px] top-1/2 hidden h-[520px] w-[520px] -translate-y-1/2 opacity-80 xl:block" aria-hidden
        style={{ maskImage: "linear-gradient(90deg, transparent 10%, #000 50%)", WebkitMaskImage: "linear-gradient(90deg, transparent 10%, #000 50%)" }}>
        {[{ s: 520, d: "38s", n: 3 }, { s: 380, d: "26s", n: 2, rev: true }, { s: 250, d: "18s", n: 2 }].map((o, i) => (
          <div key={i} className="absolute left-1/2 top-1/2" style={{ width: o.s, height: o.s, marginLeft: -o.s / 2, marginTop: -o.s / 2 }}>
            <div className="absolute inset-0 rounded-full border border-white/[0.07]" />
            <div className={o.rev ? "auth-spin-rev absolute inset-0" : "auth-spin absolute inset-0"} style={{ animationDuration: o.d }}>
              {Array.from({ length: o.n }).map((_, k) => (
                <span key={k} className="absolute left-1/2 top-1/2 h-0 w-0" style={{ transform: `rotate(${(360 / o.n) * k + i * 40}deg) translateY(${-o.s / 2}px)` }}>
                  <span className="auth-node absolute -left-[5px] -top-[5px] h-2.5 w-2.5 rounded-full bg-[#a99bff]" style={{ animationDelay: `${k * 0.7 + i * 0.4}s` }} />
                </span>
              ))}
            </div>
          </div>
        ))}
        <div className="absolute left-1/2 top-1/2 -ml-[46px] -mt-[46px] flex h-[92px] w-[92px] items-center justify-center rounded-2xl border border-white/10 bg-[#0d1020]">
          <span className="auth-core-ring absolute inset-0 rounded-2xl border border-[#a99bff]/40" />
          <ShieldCheck className="h-9 w-9 text-[#a99bff]" strokeWidth={1.5} />
        </div>
      </div>

      <div className="relative flex h-full flex-col justify-between p-10">
        <div className="dark auth-rise" style={{ animationDelay: "0ms" }}><Wordmark /></div>
        <div className="max-w-md">
          <p className="auth-rise mb-3 text-xs font-medium uppercase tracking-[0.2em] text-[#a99bff]" style={{ animationDelay: "80ms" }}>Continuous authorization</p>
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            {HEADLINE.map((w, i) => (
              <span key={i} className="inline-block overflow-hidden pb-1 align-bottom"><span className="auth-word inline-block" style={{ animationDelay: `${140 + i * 55}ms` }}>{w}&nbsp;</span></span>
            ))}
          </h2>
          <div className="mt-8 space-y-4 text-sm text-white/70">
            {FEATURES.map(([I, t], i) => (
              <div key={t} className="auth-rise flex items-center gap-3" style={{ animationDelay: `${620 + i * 90}ms` }}>
                <span className="rounded-md border border-white/10 bg-white/5 p-1.5"><I className="h-4 w-4 text-[#a99bff]" /></span>{t}
              </div>
            ))}
          </div>
        </div>
        <p className="auth-rise text-xs text-white/40" style={{ animationDelay: "1000ms" }}>Nexora Technologies · Simulated enterprise environment · No real systems or personal data</p>
      </div>
    </div>
  );
}
