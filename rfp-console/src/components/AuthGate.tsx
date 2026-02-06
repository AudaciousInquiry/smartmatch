"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

const PUBLIC_PATHS = new Set(["/auth/signin"]);

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  const isPublic = pathname ? PUBLIC_PATHS.has(pathname) : false;

  useEffect(() => {
    if (!isPublic && status === "unauthenticated") {
      router.replace("/auth/signin");
    }
  }, [isPublic, router, status]);

  if (isPublic) return <>{children}</>;
  if (status === "loading") return null;
  if (status === "unauthenticated") return null;

  return <>{children}</>;
}
