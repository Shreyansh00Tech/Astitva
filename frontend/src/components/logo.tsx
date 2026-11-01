import { useId } from "react";

/**
 * ASTITVA mark: an "A" that doubles as a shield roof over a person (identity),
 * with a small node on the apex for the AI agents it governs. Violet-to-indigo tile.
 */
export function Logo({ size = 28 }: { size?: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <defs>
        <linearGradient id={`${id}-bg`} x1="2" y1="1" x2="30" y2="31" gradientUnits="userSpaceOnUse">
          <stop stopColor="#8B6CFF" />
          <stop offset=".55" stopColor="#5B3DF0" />
          <stop offset="1" stopColor="#2E1F9E" />
        </linearGradient>
        <linearGradient id={`${id}-sh`} x1="16" y1="0" x2="16" y2="16" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" stopOpacity=".28" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id}-bg)`} />
      <rect x=".5" y=".5" width="31" height="31" rx="8.5" stroke="#fff" strokeOpacity=".16" />
      <path d="M2 9a7 7 0 0 1 7-7h14a7 7 0 0 1 7 7v2C22 15 10 15 2 11V9Z" fill={`url(#${id}-sh)`} />
      {/* the A / shield roof */}
      <path d="M7.2 24.6 16 7.4l8.8 17.2" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      {/* identity: head and shoulders sheltered under the roof */}
      <circle cx="16" cy="17.1" r="2.15" fill="#fff" />
      <path d="M12.4 23.4c.5-2 1.9-3.1 3.6-3.1s3.1 1.1 3.6 3.1" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
      {/* AI node on the apex */}
      <circle cx="16" cy="7.4" r="2.1" fill="#C4B5FD" stroke="#fff" strokeWidth="1.3" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <Logo size={30} />
      <div className="leading-none">
        <div className="text-[13.5px] font-bold tracking-[0.2em]">
          ASTI<span className="bg-gradient-to-r from-violet to-indigo-500 bg-clip-text text-transparent">TVA</span>
        </div>
        <div className="mt-1 text-[9.5px] font-medium uppercase tracking-[0.12em] text-muted-foreground">Identity · Access · AI</div>
      </div>
    </div>
  );
}
