import { useEffect, useState } from "react";

interface ScheduleCardProps {
  onClose: () => void;
  onSubmit: (schedule: { hour: number; minute: number; frequency: number }) => Promise<void> | void;
  schedule?: {
    enabled?: boolean;
    interval_hours?: number;
    next_run_at?: string | null;
  };
}

export function ScheduleCard({ onClose, onSubmit, schedule }: ScheduleCardProps) {
  const [hour, setHour] = useState<number>(() => {
    const d = schedule?.next_run_at ? new Date(schedule.next_run_at) : new Date();
    return d.getHours();
  });
  const [minute, setMinute] = useState<number>(() => {
    const d = schedule?.next_run_at ? new Date(schedule.next_run_at) : new Date();
    return Math.round(d.getMinutes() / 5) * 5 % 60;
  });
  const [frequency, setFrequency] = useState<number>(schedule?.interval_hours ?? 24);
  const [timeLeft, setTimeLeft] = useState<{ h: number; m: number } | null>(null);

  useEffect(() => {
    function calc() {
      if (!schedule?.next_run_at) {
        setTimeLeft(null);
        return;
      }
      const next = new Date(schedule.next_run_at);
      const now = new Date();
      const diff = Math.max(0, next.getTime() - now.getTime());
      const h = Math.floor(diff / (1000 * 60 * 60));
      const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      setTimeLeft({ h, m });
    }
    calc();
    const id = setInterval(calc, 30_000);
    return () => clearInterval(id);
  }, [schedule?.next_run_at]);

  const frequencies = [
    { label: "Every 3 minutes", value: 3 / 60 },
    { label: "Every 10 minutes", value: 10 / 60 },
    { label: "Every 30 minutes", value: 30 / 60 },
    { label: "Every 60 minutes", value: 60 / 60 },
    { label: "Every 6 hours", value: 6 },
    { label: "Every 12 hours", value: 12 },
    { label: "Daily", value: 24 },
    { label: "Every 2 days", value: 48 },
    { label: "Every 3 days", value: 72 },
    { label: "Weekly", value: 168 },
  ];

  return (
    <div className="w-80 bg-gray-800/95 rounded-xl border border-gray-700/50 shadow-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-400">Next run</p>
          <p className="text-sm text-white">
            {timeLeft ? `${timeLeft.h}h ${timeLeft.m}m` : "Not scheduled"}
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-sm text-gray-300 hover:text-white"
          aria-label="Close schedule"
        >
          ×
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-sm text-gray-400">Hour</label>
          <select
            value={hour}
            onChange={(e) => setHour(Number(e.target.value))}
            className="w-full bg-gray-700/60 text-gray-200 rounded-lg border border-gray-600/50 px-3 py-2"
          >
            {Array.from({ length: 24 }).map((_, i) => (
              <option key={i} value={i}>
                {i.toString().padStart(2, "0")}:00
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-sm text-gray-400">Minute</label>
          <select
            value={minute}
            onChange={(e) => setMinute(Number(e.target.value))}
            className="w-full bg-gray-700/60 text-gray-200 rounded-lg border border-gray-600/50 px-3 py-2"
          >
            {Array.from({ length: 12 }).map((_, i) => {
              const val = i * 5;
              return (
                <option key={val} value={val}>
                  {val.toString().padStart(2, "0")}
                </option>
              );
            })}
          </select>
        </div>
      </div>

      <div>
        <label className="text-sm text-gray-400">Frequency</label>
        <select
          value={frequency}
          onChange={(e) => setFrequency(Number(e.target.value))}
          className="w-full bg-gray-700/60 text-gray-200 rounded-lg border border-gray-600/50 px-3 py-2"
        >
          {frequencies.map((f) => (
            <option key={String(f.value)} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex justify-end pt-2">
        <button
          onClick={() => onSubmit({ hour, minute, frequency })}
          className="rounded-lg bg-blue-600/80 text-white px-4 py-2"
        >
          Apply Schedule
        </button>
      </div>
    </div>
  );
}