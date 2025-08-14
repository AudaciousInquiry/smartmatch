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
  
  const [sortField, setSortField] = useState<keyof RfpRow>("processed_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  
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

  const handleSort = (field: keyof RfpRow) => {
    if (field === sortField) {
      // Toggle direction if same field
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      // New field, default to descending for dates, ascending for text
      setSortField(field);
      setSortDirection(field === "processed_at" ? "desc" : "asc");
    }
  };

  const sortedRows = useMemo(() => {
    if (!rows.length) return rows;
    
    return [...rows].sort((a, b) => {
      let aVal = a[sortField];
      let bVal = b[sortField];
      
      // Handle null/undefined values
      if (aVal === null || aVal === undefined) aVal = "";
      if (bVal === null || bVal === undefined) bVal = "";
      
      // Convert to strings for comparison
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      
      // For dates, convert to timestamp for proper sorting
      if (sortField === "processed_at") {
        const aTime = new Date(aVal as string).getTime();
        const bTime = new Date(bVal as string).getTime();
        return sortDirection === "asc" ? aTime - bTime : bTime - aTime;
      }
      
      // For other fields, use string comparison
      if (aStr < bStr) return sortDirection === "asc" ? -1 : 1;
      if (aStr > bStr) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });
  }, [rows, sortField, sortDirection]);

  const SortIcon = ({ field }: { field: keyof RfpRow }) => {
    if (sortField !== field) {
      return (
        <span className="ml-2 text-gray-400 opacity-50">
          <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
        </span>
      );
    }
    
    return (
      <span className="ml-2 text-blue-400">
        {sortDirection === "asc" ? (
          <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4l6 6 6-6" />
          </svg>
        ) : (
          <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 20l-6-6-6 6" />
          </svg>
        )}
      </span>
    );
  };

  const table = useMemo(
    () => (
      <div className="overflow-x-auto rounded-xl border border-gray-700/50 bg-gray-800/50 backdrop-blur-sm shadow-xl">
        <table className="min-w-[900px] w-full text-sm">
          <thead className="bg-gray-700/80 text-gray-100 border-b border-gray-600/50">
            <tr>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("processed_at")}
              >
                Date Found
                <SortIcon field="processed_at" />
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("site")}
              >
                Source
                <SortIcon field="site" />
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("title")}
              >
                Name of Opportunity
                <SortIcon field="title" />
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("url")}
              >
                Link
                <SortIcon field="url" />
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("hash")}
              >
                Hash
                <SortIcon field="hash" />
              </th>
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {sortedRows.map((r, index) => (
              <tr key={r.hash} className={`border-t border-gray-700/30 hover:bg-gray-700/30 transition-colors ${index % 2 === 0 ? 'bg-gray-800/20' : 'bg-gray-800/40'}`}>
                <td className="p-4 whitespace-nowrap text-gray-300">{fmt(r.processed_at)}</td>
                <td className="p-4 text-blue-400 font-medium">{r.site}</td>
                <td className="p-4">{r.title}</td>
                <td className="p-4">
                  <a href={r.url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 underline decoration-blue-400/50 hover:decoration-blue-300 transition-colors">
                    {r.url}
                  </a>
                </td>
                <td className="p-4 font-mono text-xs text-gray-400 bg-gray-900/30 rounded">{r.hash.slice(0, 10)}…</td>
              </tr>
            ))}
            {!sortedRows.length && !loading && (
              <tr>
                <td className="p-8 text-center text-gray-400" colSpan={5}>
                  No rows found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    ),
    [sortedRows, loading]
  );

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6 space-y-8">
      <header className="flex items-center justify-between bg-gray-800/60 backdrop-blur-sm rounded-xl p-6 border border-gray-700/50 shadow-lg">
        <h1 className="text-3xl font-bold text-white">SmartMatch Admin Console</h1>
        <div className="space-x-3">
          <button
            onClick={load}
            disabled={loading}
            className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-2 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
          <button
            onClick={onRunNow}
            disabled={running}
            className="rounded-lg bg-blue-600/80 text-white border border-blue-500/50 px-4 py-2 hover:bg-blue-500/90 hover:border-blue-400/70 active:bg-blue-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
          >
            {running ? "Running…" : "Run Now"}
          </button>
        </div>
      </header>

      <form onSubmit={onSearch} className="flex gap-3 bg-gray-800/40 backdrop-blur-sm rounded-xl p-4 border border-gray-700/50 shadow-lg">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search via date, source, name, link, or hash..."
          className="flex-1 max-w-md rounded-lg bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 backdrop-blur-sm transition-all duration-200"
        />
        <button className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-3 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md">
          Search
        </button>
      </form>

      {table}
    </main>
  );
}
