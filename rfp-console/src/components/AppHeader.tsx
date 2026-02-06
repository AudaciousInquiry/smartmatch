"use client";

import { usePathname } from "next/navigation";
import { AuthButton } from "./AuthButton";

export function AppHeader() {
  const pathname = usePathname();

  if (pathname === "/auth/signin") return null;

  return (
    <header className="sticky top-0 z-50 border-b border-gray-800 bg-gray-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div className="text-sm font-semibold text-gray-200">SmartMatch Admin</div>
        <AuthButton />
      </div>
    </header>
  );
}
