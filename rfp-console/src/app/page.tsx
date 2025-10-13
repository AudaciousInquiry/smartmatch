"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { listRfps, triggerScrape, type RfpRow, updateSchedule, getSchedule, clearSchedule, getEmailSettings, setEmailSettings } from "./lib/api";
import { 
  RefreshIcon, 
  CalendarIcon, 
  LightningIcon, 
  TrashIcon, 
  SortIcon 
} from "../components/Icons";
import { DetailView } from "../components/DetailView";
import { getRfpDetail, downloadPdf, RfpDetailRow } from './lib/api';
import { ScheduleCard } from "../components/ScheduleCard";
import { MailingListCard } from "../components/MailingListCard";
import { Notification, NotificationType } from "../components/Notification";

// Format timestamp strings 
function fmt(dt: string | null) {
  if (!dt) return "";
  const d = new Date(dt);
  if (Number.isNaN(d.getTime())) return dt;
  return d.toLocaleString();
}

export default function Home() {
  //  RFP listing state 
  const [rows, setRows] = useState<RfpRow[]>([]);
  const [loading, setLoading] = useState(false);
  //  Scrape triggers 
  const [running, setRunning] = useState(false);
  //  Schedule panel 
  const [showSchedule, setShowSchedule] = useState(false);
  const [schedule, setSchedule] = useState<any | null>(null);
  const [scheduling, setScheduling] = useState(false);
  //  Mailing lists 
  const [showMailing, setShowMailing] = useState(false);
  const [mailing, setMailing] = useState<{ main_recipients: string[]; debug_recipients: string[] } | null>(null);
  // (q reserved for future server-side search)
  const [q, setQ] = useState("");  
  //  Sorting / filtering 
  const [sortField, setSortField] = useState<keyof RfpRow>("processed_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [filterText, setFilterText] = useState("");
  //  Detail view 
  const [selectedRow, setSelectedRow] = useState<RfpDetailRow | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  //  Notifications
  const [notification, setNotification] = useState<{ message: string; type: NotificationType } | null>(null);
  
  const scheduleRef = useRef<HTMLDivElement>(null);
  const mailingRef = useRef<HTMLDivElement>(null);
  
  const showNotification = (message: string, type: NotificationType) => {
    setNotification({ message, type });
  };
  
  // Fetch current RFP rows (limit 500)
  const load = async () => {
    setLoading(true);
    try {
      const res = await listRfps({ q, limit: 500, sort: "processed_at", order: "desc" });
      setRows(res.data);
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => { load(); }, []);

  // Fetch schedule + email settings once on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await getSchedule();
        setSchedule(res.data); // Will be null if 404
        if (res.data === null) {
          showNotification("No schedule is currently set. Please create a schedule to enable automated runs.", "warning");
        }
      } catch (e) {
        // Only log unexpected errors
        console.error("Unexpected error loading schedule", e);
      }
      try {
        const m = await getEmailSettings();
        setMailing(m.data);
      } catch (e) {
        console.error("Failed to load email settings", e);
      }
    })();
  }, []);

  // Manual scrape trigger (also triggers emails)
  const onRunNow = async () => {
    setRunning(true);
    try {
      const res = await triggerScrape(true, true);
      showNotification(`Scrape complete. Found ${res.data.new_count} new RFPs.`, "success");
      await load();
    } finally {
      setRunning(false);
    }
  };

  // Open schedule panel OR submit new schedule settings
  const onScheduleRun = async (payload?: { hour: number; minute: number; frequency: number }) => {
    if (!payload) {
      setShowSchedule(!showSchedule);
      return;
    }
    setScheduling(true);
    try {
      const body = {
        enabled: true,
        interval_hours: payload.frequency,
        next_run_hour: payload.hour,
        next_run_minute: payload.minute,
      };
      await updateSchedule(body);
      const refreshed = await getSchedule();
      setSchedule(refreshed.data);
      setShowSchedule(false);
      showNotification("Schedule updated successfully!", "success");
    } catch (error: any) {
      const detail = error?.response?.data ?? error?.message ?? "Unknown error";
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      console.error("Schedule update error:", msg);
      showNotification("Failed to update schedule: " + msg, "error");
    } finally {
      setScheduling(false);
    }
  };

  // Disable scheduling (clears next/last run)
  const onClearSchedule = async () => {
    setScheduling(true);
    try {
      const res = await clearSchedule();
      setSchedule(res.data);
      showNotification("Schedule cleared successfully", "success");
    } catch (error: any) {
      showNotification("Failed to clear schedule: " + (error?.response?.data?.detail ?? error?.message), "error");
    } finally {
      setScheduling(false);
    }
  };

  // Toggle sort direction or set new sort field (stable for ties)
  const handleSort = (field: keyof RfpRow) => {
    if (field === sortField) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection(field === "processed_at" ? "desc" : "asc");
    }
  };

  // Derive table rows => filter then sort; memoized to avoid rework on unrelated state changes
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

  // Load full detail (and switch panel) when selecting a row
  const handleRowClick = async (hash: string) => {
    setLoadingDetail(true);
    try {
      const res = await getRfpDetail(hash);
      setSelectedRow(res.data);
    } catch (error) {
      showNotification('Failed to load details', 'error');
    } finally {
      setLoadingDetail(false);
    }
  };

  // Request PDF bytes from DB and trigger download
  const handleDownloadPdf = async () => {
    if (!selectedRow) return;
    
    try {
      const res = await downloadPdf(selectedRow.hash);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${selectedRow.title}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      showNotification('PDF downloaded successfully', 'success');
    } catch (error) {
      showNotification('Failed to download PDF', 'error');
    }
  };

  // Memoized tbody element (depends on filtered list + click handler)
  const tableRows = useMemo(() => (
    <tbody className="text-gray-200">
      {filteredAndSortedRows.map((r, index) => (
        <tr 
          key={r.hash} 
          onClick={() => handleRowClick(r.hash)}
          className={`border-t border-gray-700/30 hover:bg-gray-700/30 transition-colors cursor-pointer ${
            index % 2 === 0 ? 'bg-gray-800/20' : 'bg-gray-800/40'
          }`}
        >
          <td className="p-4 whitespace-nowrap">
            {fmt(r.processed_at)}
          </td>
          <td className="p-4 whitespace-nowrap">
            {r.site}
          </td>
          <td className="p-4 whitespace-nowrap">
            {r.title}
          </td>
          <td className="p-4 whitespace-nowrap">
            <a 
              href={r.url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-blue-400 hover:underline"
            >
              {r.url}
            </a>
          </td>
          <td className="p-4 whitespace-nowrap">
            {r.hash}
          </td>
        </tr>
      ))}
    </tbody>
  ), [filteredAndSortedRows, handleRowClick]);

  // Outer table wrapper (headers separated for clarity / sorting)
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
          {tableRows}
        </table>
      </div>
    ),
    [filteredAndSortedRows, loading]
  );

  // Dismiss floating panels when clicking elsewhere
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (scheduleRef.current && !scheduleRef.current.contains(event.target as Node)) {
        setShowSchedule(false);
      }
      if (mailingRef.current && !mailingRef.current.contains(event.target as Node)) {
        setShowMailing(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6 space-y-8">
      {notification && createPortal(
        <Notification
          message={notification.message}
          type={notification.type}
          onClose={() => setNotification(null)}
        />,
        document.body
      )}
      <header className="flex items-center justify-between bg-gray-800/60 backdrop-blur-sm rounded-xl p-6 border border-gray-700/50 shadow-lg">
        <h1 className="text-3xl font-bold text-white">SmartMatch Admin Console</h1>
        <div className="flex items-center gap-3"> 
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
          <div className="relative inline-block"> 
            <button
              onClick={() => onScheduleRun()}
              disabled={scheduling}
              className="rounded-lg bg-purple-600/80 text-white border border-purple-500/50 px-4 py-2 hover:bg-purple-500/90 hover:border-purple-400/70 active:bg-purple-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
            >
              <span className="flex items-center gap-2">
                <CalendarIcon />
                {scheduling ? "Scheduling…" : "Schedule Run"}
              </span>
            </button>
            
            {showSchedule && createPortal(
              <div ref={scheduleRef} className="fixed top-20 right-6 z-[99999]">
                <div className="bg-gray-800/95 rounded-xl border border-gray-700/50 shadow-xl">
                  <ScheduleCard
                    onClose={() => setShowSchedule(false)}
                    onSubmit={onScheduleRun}
                    onClear={onClearSchedule}
                    schedule={schedule}
                  />
                </div>
              </div>,
              document.body
            )}
          </div>
          <div className="relative inline-block">
            <button
              onClick={async () => {
                try {
                  const m = await getEmailSettings();
                  setMailing(m.data);
                  setShowMailing(true);
                } catch (e) {
                  showNotification("Failed to load mailing lists", "error");
                }
              }}
              className="rounded-lg bg-teal-600/80 text-white border border-teal-500/50 px-4 py-2 hover:bg-teal-500/90 hover:border-teal-400/70 active:bg-teal-700/90 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md"
            >
              Mailing Lists
            </button>
            {showMailing && mailing && createPortal(
              <div ref={mailingRef} className="fixed top-20 right-6 z-[99999]">
                <MailingListCard
                  initial={mailing}
                  onClose={() => setShowMailing(false)}
                  onSave={async (settings) => {
                    await setEmailSettings(settings);
                    setMailing(settings);
                  }}
                />
              </div>,
              document.body
            )}
          </div>
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

  {selectedRow ? (
        <DetailView 
          data={selectedRow}
          onBack={() => setSelectedRow(null)}
          onDownload={handleDownloadPdf}
        />
      ) : (
        <>
          <div className="bg-gray-800/40 rounded-xl p-6 border border-gray-700/50 shadow-lg space-y-4">
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
        </>
      )}
    </main>
  );
}
/* test change */
