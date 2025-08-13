"use client";

import { useEffect, useMemo, useState } from "react";
import { listRfps, triggerScrape, type RfpRow } from "./lib/api";

function fmt(dt: string | null) {
  if (!dt) return "";
  const d = new Date(dt);
  if (Number.isNaN(d.getTime())) return dt;
  return d.toLocaleString();
}

export default function Home() {
  const [rows, setRows] = useState<RfpRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [q, setQ] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const res = await listRfps({ q, limit: 200, sort: "processed_at", order: "desc" });
      setRows(res.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    await load();
  };

  const onRunNow = async () => {
    setRunning(true);
    try {
      const res = await triggerScrape(true, true);
      alert(`Scrape complete. Found ${res.data.new_count} new RFPs.`);
      await load();
    } finally {
      setRunning(false);
    }
  };

  const table = useMemo(
    () => (
      <div className="overflow-x-auto rounded-xl border">
        <table className="min-w-[900px] w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="p-3 text-left">Processed At</th>
              <th className="p-3 text-left">Site</th>
              <th className="p-3 text-left">Title</th>
              <th className="p-3 text-left">URL</th>
              <th className="p-3 text-left">Hash</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.hash} className="border-t">
                <td className="p-3 whitespace-nowrap">{fmt(r.processed_at)}</td>
                <td className="p-3">{r.site}</td>
                <td className="p-3">{r.title}</td>
                <td className="p-3">
                  <a href={r.url} target="_blank" rel="noreferrer" className="underline">
                    {r.url}
                  </a>
                </td>
                <td className="p-3 font-mono text-xs">{r.hash.slice(0, 10)}…</td>
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr>
                <td className="p-6 text-center text-gray-500" colSpan={5}>
                  No rows
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    ),
    [rows, loading]
  );

  return (
    <main className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">SmartMatch Admin</h1>
        <div className="space-x-2">
          <button
            onClick={load}
            disabled={loading}
            className="rounded-lg border px-3 py-2 hover:bg-gray-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
          <button
            onClick={onRunNow}
            disabled={running}
            className="rounded-lg bg-black text-white px-3 py-2 hover:opacity-90"
          >
            {running ? "Running…" : "Run Now"}
          </button>
        </div>
      </header>

      <form onSubmit={onSearch} className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search title/site/url…"
          className="w-80 rounded-lg border px-3 py-2"
        />
        <button className="rounded-lg border px-3 py-2 hover:bg-gray-50">Search</button>
      </form>

      {table}
    </main>
  );
}
