import { Wordmark } from "@/components/logo";
import { AuthVisual } from "@/components/auth-visual";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <AuthVisual />
      <div className="relative flex items-center justify-center overflow-hidden px-4 py-10 sm:px-8">
        <div className="auth-form-glow pointer-events-none absolute left-1/2 top-1/2 h-[520px] w-[520px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ background: "radial-gradient(circle, hsl(var(--violet) / .09), transparent 65%)" }} />
        <div className="auth-card relative w-full max-w-[380px]">
          <div className="mb-8 lg:hidden"><Wordmark /></div>
          {children}
        </div>
      </div>
    </div>
  );
}
