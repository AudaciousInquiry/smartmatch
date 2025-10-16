import { TrashIcon } from './Icons';

interface ConfirmDialogProps {
  title: string;
  message: string;
  itemName?: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading?: boolean;
  confirmText?: string;
  cancelText?: string;
}

export function ConfirmDialog({
  title,
  message,
  itemName,
  onConfirm,
  onCancel,
  isLoading = false,
  confirmText = "Delete",
  cancelText = "Cancel"
}: ConfirmDialogProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9998]"
        onClick={onCancel}
      />

      {/* Dialog */}
      <div className="fixed inset-0 flex items-center justify-center z-[9999]">
        <div className="bg-gray-800/95 rounded-2xl border border-gray-700/50 shadow-2xl p-8 max-w-md w-full mx-4 backdrop-blur-md">
          {/* Header with icon */}
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-full bg-red-600/20 border border-red-500/30 flex items-center justify-center flex-shrink-0">
              <TrashIcon />
            </div>
            <h2 className="text-xl font-bold text-white">{title}</h2>
          </div>

          {/* Message */}
          <div className="mb-6">
            <p className="text-gray-300 text-sm leading-relaxed">{message}</p>
            {itemName && (
              <p className="text-gray-200 font-semibold mt-2 px-3 py-2 bg-gray-700/30 rounded-lg border border-gray-600/30">
                "{itemName}"
              </p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex gap-3 justify-end">
            <button
              onClick={onCancel}
              disabled={isLoading}
              className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-2 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
            >
              {cancelText}
            </button>
            <button
              onClick={onConfirm}
              disabled={isLoading}
              className="rounded-lg bg-red-600/80 text-white border border-red-500/50 px-4 py-2 hover:bg-red-500/90 hover:border-red-400/70 active:bg-red-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
            >
              <TrashIcon />
              {isLoading ? "Deleting…" : confirmText}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
