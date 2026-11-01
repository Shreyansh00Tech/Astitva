import { NextResponse, type NextRequest } from "next/server";

// UX-only redirect. Real authorization happens in the FastAPI backend on every request.
const PUBLIC = ["/login", "/register", "/verify-email", "/forgot-password", "/reset-password"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname.startsWith("/api") || pathname.startsWith("/_next") || pathname.includes(".")) return NextResponse.next();
  const hasSession = req.cookies.has("astitva_csrf") || req.cookies.has("astitva_at");
  if (!hasSession && !PUBLIC.some((p) => pathname.startsWith(p))) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Node.js runtime: Vercel Services do not run Edge functions.
  runtime: "nodejs",
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
