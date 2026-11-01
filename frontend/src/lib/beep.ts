"use client";

/**
 * One soft, short beep for the Security Manager when break-glass (emergency) access is activated.
 * Synthesised with Web Audio, so there is no sound file. Plays once per event, never loops.
 */
let ctx: AudioContext | null = null;
const played = new Set<string>();
const LOCK_KEY = "astitva:emergency-beep";
const COOLDOWN_MS = 4000;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext || (window as any).webkitAudioContext;
  if (!Ctor) return null;
  ctx = ctx || new Ctor();
  return ctx;
}

/** Browsers only allow sound after a user gesture; unlock the audio context on the first click or key press. */
export function primeBeep() {
  const unlock = () => { audio()?.resume().catch(() => {}); };
  window.addEventListener("pointerdown", unlock, { once: true });
  window.addEventListener("keydown", unlock, { once: true });
  return () => { window.removeEventListener("pointerdown", unlock); window.removeEventListener("keydown", unlock); };
}

/** Plays the beep at most once per notification id, and only once across open tabs within a few seconds. */
export function emergencyBeep(id: string) {
  if (played.has(id)) return;
  played.add(id);
  try {
    const last = Number(localStorage.getItem(LOCK_KEY) || 0);
    if (Date.now() - last < COOLDOWN_MS) return;
    localStorage.setItem(LOCK_KEY, String(Date.now()));
  } catch { /* storage blocked: the per-tab guard above still applies */ }
  const ac = audio();
  if (!ac) return;
  if (ac.state === "suspended") ac.resume().catch(() => {});
  const t = ac.currentTime + 0.02;
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(660, t);
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.06, t + 0.03); // low volume
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35); // soft fade-out
  osc.connect(gain).connect(ac.destination);
  osc.start(t);
  osc.stop(t + 0.4);
}
