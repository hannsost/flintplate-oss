/**
 * Next.js proxy – route guard stub.
 *
 * Auth state lives in localStorage (client-only), so true server-side
 * protection requires an HttpOnly cookie in a later sprint. For now this
 * proxy just defines the protected matcher so the structure is in place.
 *
 * Sprint 0.3+: move token to HttpOnly cookie and validate here.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(_request: NextRequest) {
  // Pass-through: client components handle redirects via auth.isLoggedIn()
  return NextResponse.next();
}

export const config = {
  matcher: ["/profile/:path*"],
};
