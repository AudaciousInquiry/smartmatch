"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getWebsiteSettings, addWebsite, updateWebsite, deleteWebsite, type WebsiteSetting } from "../app/lib/api";
import { Notification, NotificationType } from "./Notification";
import { ConfirmDialog } from "./ConfirmDialog";
import { createPortal } from "react-dom";
import { TrashIcon, BackIcon } from "./Icons";

export function WebsiteSettings() {
  const router = useRouter();
  const [websites, setWebsites] = useState<WebsiteSetting[]>([]);
  const [loading, setLoading] = useState(true);
  const [notification, setNotification] = useState<{ message: string; type: NotificationType } | null>(null);
  
  // Form state for adding/editing
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formName, setFormName] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; name: string } | null>(null);

  const showNotification = (message: string, type: NotificationType) => {
    setNotification({ message, type });
  };

  const loadWebsites = async () => {
    setLoading(true);
    try {
      const res = await getWebsiteSettings();
      setWebsites(res.data);
    } catch (error: any) {
      // If 404, it means the table is empty or doesn't exist yet - treat as empty list
      if (error?.response?.status === 404) {
        setWebsites([]);
      } else {
        showNotification('Failed to load website settings', 'error');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadWebsites();
  }, []);

  const handleAdd = async () => {
    if (!formName.trim() || !formUrl.trim()) {
      showNotification('Name and URL are required', 'warning');
      return;
    }

    setSaving(true);
    try {
      await addWebsite({
        name: formName.trim(),
        url: formUrl.trim(),
        enabled: formEnabled,
      });
      showNotification('Website added successfully', 'success');
      setFormName("");
      setFormUrl("");
      setFormEnabled(true);
      await loadWebsites();
    } catch (error) {
      showNotification('Failed to add website', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (editingId === null) return;
    if (!formName.trim() || !formUrl.trim()) {
      showNotification('Name and URL are required', 'warning');
      return;
    }

    setSaving(true);
    try {
      await updateWebsite(editingId, {
        name: formName.trim(),
        url: formUrl.trim(),
        enabled: formEnabled,
      });
      showNotification('Website updated successfully', 'success');
      setEditingId(null);
      setFormName("");
      setFormUrl("");
      setFormEnabled(true);
      await loadWebsites();
    } catch (error) {
      showNotification('Failed to update website', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (id: number, name: string) => {
    setDeleteConfirm({ id, name });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm) return;

    try {
      await deleteWebsite(deleteConfirm.id);
      showNotification('Website deleted successfully', 'success');
      setDeleteConfirm(null);
      await loadWebsites();
    } catch (error) {
      showNotification('Failed to delete website', 'error');
    }
  };

  const handleEdit = (website: WebsiteSetting) => {
    setEditingId(website.id);
    setFormName(website.name);
    setFormUrl(website.url);
    setFormEnabled(website.enabled);
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setFormName("");
    setFormUrl("");
    setFormEnabled(true);
  };

  const handleToggleEnabled = async (website: WebsiteSetting) => {
    try {
      await updateWebsite(website.id, { enabled: !website.enabled });
      showNotification(`Website ${!website.enabled ? 'enabled' : 'disabled'}`, 'success');
      await loadWebsites();
    } catch (error) {
      showNotification('Failed to update website status', 'error');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-white text-xl">Loading website settings...</div>
      </div>
    );
  }

  return (
    <>
      {notification && createPortal(
        <Notification
          message={notification.message}
          type={notification.type}
          onClose={() => setNotification(null)}
        />,
        document.body
      )}

      {deleteConfirm && createPortal(
        <ConfirmDialog
          title="Delete Website"
          message="This website will be removed from the scraper. This action cannot be undone."
          itemName={deleteConfirm.name}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteConfirm(null)}
          confirmText="Delete"
          cancelText="Cancel"
        />,
        document.body
      )}

      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white">Website Settings</h2>
            <p className="text-sm text-gray-400 mt-1">Configure which websites to scrape for RFPs</p>
          </div>
          <button
            onClick={() => router.push('/')}
            className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-2 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md"
          >
            <span className="flex items-center gap-2">
              <BackIcon />
              Back to Main
            </span>
          </button>
        </div>

        {/* Add/Edit Form */}
        <div className="bg-gray-800/40 rounded-xl p-6 border border-gray-700/50 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-4">
            {editingId ? 'Edit Website' : 'Add New Website'}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Name
              </label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g., CDC Foundation"
                className="w-full rounded-lg bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 backdrop-blur-sm transition-all duration-200"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                URL
              </label>
              <input
                type="text"
                value={formUrl}
                onChange={(e) => setFormUrl(e.target.value)}
                placeholder="https://example.com/rfps"
                className="w-full rounded-lg bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 backdrop-blur-sm transition-all duration-200"
              />
            </div>
          </div>
          <div className="mt-4 flex items-center gap-4">
            <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={formEnabled}
                onChange={(e) => setFormEnabled(e.target.checked)}
                className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-2 focus:ring-blue-500/50"
              />
              <span className="text-sm">Enabled</span>
            </label>
          </div>
          <div className="mt-4 flex gap-3">
            {editingId ? (
              <>
                <button
                  onClick={handleUpdate}
                  disabled={saving}
                  className="rounded-lg bg-blue-600/80 text-white border border-blue-500/50 px-4 py-2 hover:bg-blue-500/90 hover:border-blue-400/70 active:bg-blue-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
                >
                  {saving ? 'Saving...' : 'Update Website'}
                </button>
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-2 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={handleAdd}
                disabled={saving}
                className="rounded-lg bg-green-600/80 text-white border border-green-500/50 px-4 py-2 hover:bg-green-500/90 hover:border-green-400/70 active:bg-green-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md"
              >
                {saving ? 'Adding...' : 'Add Website'}
              </button>
            )}
          </div>
        </div>

        {/* Website List */}
        <div className="bg-gray-800/40 rounded-xl p-6 border border-gray-700/50 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-4">
            Configured Websites ({websites.length})
          </h3>
          {websites.length === 0 ? (
            <p className="text-gray-400 text-center py-8">
              No websites configured. Add your first website above.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-gray-700/50 bg-gray-800/50 backdrop-blur-sm shadow-xl">
              <table className="w-full text-sm">
                <thead className="bg-gray-700/80 text-gray-100 border-b border-gray-600/50">
                  <tr>
                    <th className="p-4 text-left font-medium">Name</th>
                    <th className="p-4 text-left font-medium">URL</th>
                    <th className="p-4 text-center font-medium">Status</th>
                    <th className="p-4 text-center font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-gray-200">
                  {websites.map((website, index) => (
                    <tr 
                      key={website.id}
                      className={`border-t border-gray-700/30 ${
                        index % 2 === 0 ? 'bg-gray-800/20' : 'bg-gray-800/40'
                      }`}
                    >
                      <td className="p-4">{website.name}</td>
                      <td className="p-4">
                        <a 
                          href={website.url} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:underline"
                        >
                          {website.url}
                        </a>
                      </td>
                      <td className="p-4 text-center">
                        <button
                          onClick={() => handleToggleEnabled(website)}
                          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                            website.enabled
                              ? 'bg-green-600/20 text-green-400 border border-green-500/30 hover:bg-green-600/30'
                              : 'bg-gray-600/20 text-gray-400 border border-gray-500/30 hover:bg-gray-600/30'
                          }`}
                        >
                          {website.enabled ? 'Enabled' : 'Disabled'}
                        </button>
                      </td>
                      <td className="p-4">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            onClick={() => handleEdit(website)}
                            className="rounded-lg bg-blue-600/80 text-white border border-blue-500/50 px-3 py-1 hover:bg-blue-500/90 hover:border-blue-400/70 active:bg-blue-700/90 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md text-xs"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDelete(website.id, website.name)}
                            className="rounded-lg bg-red-600/80 text-white border border-red-500/50 px-3 py-1 hover:bg-red-500/90 hover:border-red-400/70 active:bg-red-700/90 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md text-xs flex items-center gap-1"
                          >
                            <TrashIcon />
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
