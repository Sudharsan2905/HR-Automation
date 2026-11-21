import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const publicPaths = ["/", "/login"];

const rolePaths: Record<string, string[]> = {
  super_admin: ["/dashboard", "/hiring"],
  candidate: ["/exam"],
};

const roleHome: Record<string, string> = {
  super_admin: "/dashboard",
  candidate: "/exam",
};

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const role = request.cookies.get("skillmate-role")?.value;

  // The exam pages show their own access-key form, so they are open to everyone.
  if (pathname === "/exam" || pathname.startsWith("/exam/")) {
    return NextResponse.next();
  }

  if (publicPaths.includes(pathname)) {
    if (role && roleHome[role]) {
      return NextResponse.redirect(new URL(roleHome[role], request.url));
    }
    return NextResponse.next();
  }

  if (!role || !roleHome[role]) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const allowed = rolePaths[role] || [];
  const hasAccess = allowed.some((p) => pathname === p || pathname.startsWith(p + "/"));
  if (!hasAccess) {
    return NextResponse.redirect(new URL(roleHome[role], request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api|mediapipe/).*)"],
};
