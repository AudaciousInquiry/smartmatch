import { NextResponse } from "next/server";
import { auth } from "./auth";

export default auth((req) => {
  const isLoggedIn = !!req.auth;
  const { pathname } = req.nextUrl;
  const isOnSignInPage = pathname === "/auth/signin";

  if (!isLoggedIn && !isOnSignInPage) {
    return NextResponse.redirect(new URL("/auth/signin", req.nextUrl));
  }

  if (isLoggedIn && isOnSignInPage) {
    return NextResponse.redirect(new URL("/", req.nextUrl));
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
