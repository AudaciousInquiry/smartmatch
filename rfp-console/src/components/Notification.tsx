import { useEffect } from "react";

export type NotificationType = "success" | "error" | "warning" | "info";

interface NotificationProps {
  message: string;
  type: NotificationType;
  onClose: () => void;
  duration?: number;
}

export function Notification({ message, type, onClose, duration = 5000 }: NotificationProps) {
  useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(onClose, duration);
      return () => clearTimeout(timer);
    }
  }, [duration, onClose]);

  const getTypeStyles = () => {
    switch (type) {
      case "success":
        return "bg-green-600/50 border-green-500/50";
      case "error":
        return "bg-red-600/50 border-red-500/50";
      case "warning":
        return "bg-yellow-600/50 border-yellow-500/50";
      case "info":
        return "bg-blue-600/50 border-blue-500/50";
      default:
        return "bg-gray-600/50 border-gray-500/50";
    }
  };

  const getIcon = () => {
    switch (type) {
      case "success":
        return "✓";
      case "error":
        return "✕";
      case "warning":
        return "⚠";
      case "info":
        return "ℹ";
      default:
        return "";
    }
  };

  return (
    <div
      className={`fixed bottom-6 right-6 z-[99999] min-w-[320px] max-w-md rounded-xl border backdrop-blur-sm shadow-2xl p-4 flex items-start gap-3 animate-slide-in ${getTypeStyles()}`}
    >
      <div className="flex-shrink-0 text-white text-xl font-bold">
        {getIcon()}
      </div>
      <div className="flex-1">
        <p className="text-white text-sm leading-relaxed">{message}</p>
      </div>
      <button
        onClick={onClose}
        className="flex-shrink-0 text-white/80 hover:text-white text-xl leading-none transition-colors"
        aria-label="Close notification"
      >
        ×
      </button>
    </div>
  );
}
