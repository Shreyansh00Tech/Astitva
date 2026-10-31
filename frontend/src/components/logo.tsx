export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path d="M16 6.5 24.5 10v6.2c0 4.9-3.5 8.6-8.5 9.8-5-1.2-8.5-4.9-8.5-9.8V10L16 6.5Z" className="stroke-primary-foreground" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="m11.8 16.4 3 3 5.6-6.2" stroke="hsl(var(--violet))" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <Logo />
      <div className="leading-none">
        <div className="text-[13px] font-semibold tracking-[0.14em]">ASTITVA</div>
        <div className="mt-0.5 text-[10px] text-muted-foreground">Access Governance</div>
      </div>
    </div>
  );
}
