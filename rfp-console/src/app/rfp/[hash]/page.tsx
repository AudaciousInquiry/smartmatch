"use client";

import { use } from "react";
import { RfpDetailContainer } from "../../../components/RfpDetailContainer";

export default function RfpDetailPage({ params }: { params: Promise<{ hash: string }> }) {
  const { hash } = use(params);

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6 space-y-8">
      <RfpDetailContainer hash={hash} />
    </main>
  );
}
