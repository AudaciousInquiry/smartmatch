"use client";

import { useEffect, useMemo, useState } from "react";
import { listRfps, triggerScrape, type RfpRow } from "./lib/api";
import { 
  RefreshIcon, 
  CalendarIcon, 
  LightningIcon, 
  TrashIcon, 
  SortIcon 
} from "../components/Icons";

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
  const [scheduling, setScheduling] = useState(false);
  const [q, setQ] = useState("");  
  
  const [sortField, setSortField] = useState<keyof RfpRow>("processed_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [filterText, setFilterText] = useState("");
  
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

  const onScheduleRun = async () => {
    setScheduling(true);
    try {
      // Placeholder for schedule functionality
      await new Promise(resolve => setTimeout(resolve, 1000)); // Simulate API call
      alert('Mock API Call: Scrape and Email scheduled successfully!');
    } finally {
      setScheduling(false);
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

  const filteredAndSortedRows = useMemo(() => {
    // First filter the data
    let filteredRows = rows;
    
    if (filterText.trim()) {
      const searchTerm = filterText.toLowerCase().trim();
      filteredRows = rows.filter((row) => {
        // Search across all text fields
        const searchableText = [
          row.site || "",
          row.title || "",
          row.url || "",
          row.hash || "",
          fmt(row.processed_at) || ""
        ].join(" ").toLowerCase();
        
        return searchableText.includes(searchTerm);
      });
    }
    
    // Then sort the filtered results
    if (!filteredRows.length) return filteredRows;
    
    return [...filteredRows].sort((a, b) => {
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
  }, [rows, filterText, sortField, sortDirection]);

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
                <span className={`ml-2 ${sortField === 'processed_at' ? 'text-blue-400' : 'text-gray-400 opacity-50'}`}>
                  <SortIcon direction={sortField === 'processed_at' ? sortDirection : null} />
                </span>
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("site")}
              >
                Source
                <span className={`ml-2 ${sortField === 'site' ? 'text-blue-400' : 'text-gray-400 opacity-50'}`}>
                  <SortIcon direction={sortField === 'site' ? sortDirection : null} />
                </span>
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("title")}
              >
                Name of Opportunity
                <span className={`ml-2 ${sortField === 'title' ? 'text-blue-400' : 'text-gray-400 opacity-50'}`}>
                  <SortIcon direction={sortField === 'title' ? sortDirection : null} />
                </span>
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("url")}
              >
                Link
                <span className={`ml-2 ${sortField === 'url' ? 'text-blue-400' : 'text-gray-400 opacity-50'}`}>
                  <SortIcon direction={sortField === 'url' ? sortDirection : null} />
                </span>
              </th>
              <th 
                className="p-4 text-left font-medium cursor-pointer hover:bg-gray-600/50 transition-colors select-none"
                onClick={() => handleSort("hash")}
              >
                Hash
                <span className={`ml-2 ${sortField === 'hash' ? 'text-blue-400' : 'text-gray-400 opacity-50'}`}>
                  <SortIcon direction={sortField === 'hash' ? sortDirection : null} />
                </span>
              </th>
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {filteredAndSortedRows.map((r, index) => (
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
            {!filteredAndSortedRows.length && !loading && (
              <tr>
                <td className="p-8 text-center text-gray-400" colSpan={5}>
                  {filterText.trim() ? `No results found for "${filterText}"` : "No rows found"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    ),
    [filteredAndSortedRows, loading]
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
            <span className="flex items-center gap-2">
              <RefreshIcon />
              {loading ? "Loading…" : "Refresh"}
            </span>
          </button>
          <button
            onClick={onScheduleRun}
            disabled={scheduling}
            className="rounded-lg bg-purple-600/80 text-white border border-purple-500/50 px-4 py-2 hover:bg-purple-500/90 hover:border-purple-400/70 active:bg-purple-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
          >
            <span className="flex items-center gap-2">
              <CalendarIcon />
              {scheduling ? "Scheduling…" : "Schedule Run"}
            </span>
          </button>
          <button
            onClick={onRunNow}
            disabled={running}
            className="rounded-lg bg-blue-600/80 text-white border border-blue-500/50 px-4 py-2 hover:bg-blue-500/90 hover:border-blue-400/70 active:bg-blue-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
          >
            <span className="flex items-center gap-2">
              <LightningIcon />
              {running ? "Running…" : "Run Now"}
            </span>
          </button>
        </div>
      </header>

      <div className="bg-gray-800/40 backdrop-blur-sm rounded-xl p-6 border border-gray-700/50 shadow-lg space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white mb-1">Find Opportunities</h2>
            <p className="text-sm text-gray-400">Search and filter through current results</p>
          </div>
          <div className="flex items-center">
            {filterText && (
              <button
                onClick={() => setFilterText("")}
                className="rounded-lg bg-gray-600/70 text-gray-200 border border-gray-500/50 px-3 py-3 hover:bg-red-600/60 hover:text-white hover:border-red-500/50 active:bg-red-700/70 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
                title="Clear filter"
              >
                <TrashIcon />
                Clear Filter
              </button>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          <input
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Type to search..."
            className="flex-1 max-w-md rounded-lg bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-green-500/50 focus:border-green-500/50 backdrop-blur-sm transition-all duration-200"
          />
          <div className="text-sm text-gray-400">
            Displaying {filteredAndSortedRows.length} of {rows.length} opportunities
          </div>
        </div>
      </div>

      {table}
    </main>
  );
}
