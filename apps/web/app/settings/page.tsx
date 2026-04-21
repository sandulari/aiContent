"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Loading } from "@/components/shared/loading";
import { SkeletonSettings } from "@/components/shared/skeleton";
import { api, UserPage, PageType } from "@/lib/api";

export default function SettingsPage() {
  const [pages, setPages] = useState<UserPage[]>([]);
  const [newUsername, setNewUsername] = useState("");
  const [newType, setNewType] = useState<PageType>("own");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manychatKey, setManychatKey] = useState("");
  const [manychatConnected, setManychatConnected] = useState(false);
  const [savingManychat, setSavingManychat] = useState(false);

  const fetchPages = useCallback(async () => {
    try {
      setPages(await api.myPages.list());
    } catch (e: any) {
      console.error("Failed to fetch pages:", e?.message || "unknown error");
      setError(e?.message || "Failed to load pages. Please try again.");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchPages();
  }, [fetchPages]);

  const handleAdd = async () => {
    if (!newUsername.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const clean = newUsername.trim().replace(/^@/, "").replace(/^https?:\/\/(www\.)?instagram\.com\//, "").replace(/\/$/, "");
      const p = await api.myPages.add(clean, newType);
      setPages((prev) => [p, ...prev]);
      setNewUsername("");
    } catch (e: any) {
      setError(e?.message || "Could not connect page");
    }
    setAdding(false);
  };

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    try {
      await api.myPages.remove(id);
      setPages((prev) => prev.filter((p) => p.id !== id));
    } catch (e: any) {
      console.error("Failed to remove page:", e?.message || "unknown error");
      setError(e?.message || "Failed to remove page. Please try again.");
    }
    setRemovingId(null);
  };

  const handleSaveManychat = async () => {
    setSavingManychat(true);
    try {
      await api.myPages.saveIntegration("manychat", manychatKey.trim());
      setManychatConnected(true);
    } catch (e: any) {
      setError(e?.message || "Failed to save ManyChat key.");
    }
    setSavingManychat(false);
  };

  if (loading) return <SkeletonSettings />;

  const ownPages = pages.filter((p) => p.page_type === "own");
  const refPages = pages.filter((p) => p.page_type === "reference");

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-[#e6edf3]">Settings</h1>
        <p className="text-sm text-[#484f58] mt-1">Manage your connected Instagram pages</p>
      </div>

      {/* Add page form */}
      <div>
        <h2 className="text-sm font-medium text-[#e6edf3] mb-3">Connect a page</h2>
        <Card>
          <div className="space-y-3">
            <div className="flex gap-2">
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value as PageType)}
                className="h-10 px-3 text-sm bg-[#0d1117] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff]"
              >
                <option value="own">My own page</option>
                <option value="reference">Reference / inspiration</option>
              </select>
              <Input
                placeholder="Instagram username (e.g. natgeo)"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAdd()}
                className="flex-1"
              />
              <Button onClick={handleAdd} loading={adding}>Connect</Button>
            </div>
            <p className="text-[11px] text-[#484f58] leading-relaxed">
              <span className="text-[#7d8590] font-medium">My own page</span> unlocks the weekly growth dashboard.{" "}
              <span className="text-[#7d8590] font-medium">Reference</span> pages feed the similar-content engine — we surface 100+
              reels with 500K+ views based on what they post.
            </p>
            {error && <p className="text-xs text-[#f85149]">{error}</p>}
          </div>
        </Card>
      </div>

      {/* Own pages */}
      <div>
        <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
          My pages
          <span className="ml-2 text-xs text-[#484f58]">({ownPages.length})</span>
        </h2>
        <Card>
          {ownPages.length === 0 ? (
            <p className="text-xs text-[#484f58] py-4 text-center">
              Connect your own Instagram page to unlock the weekly growth dashboard.
            </p>
          ) : (
            <div className="space-y-2">
              {ownPages.map((p) => (
                <div key={p.id} className="flex items-center justify-between p-3 bg-[#0d1117] rounded-lg">
                  <div>
                    <span className="text-sm font-medium text-[#e6edf3]">@{p.ig_username}</span>
                    {p.niche && <span className="ml-2 text-xs text-[#484f58]">{p.niche}</span>}
                    {p.follower_count != null && (
                      <span className="ml-2 text-xs text-[#484f58]">{p.follower_count.toLocaleString()} followers</span>
                    )}
                  </div>
                  <Button size="sm" variant="danger" onClick={() => handleRemove(p.id)} loading={removingId === p.id}>
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Reference pages */}
      <div>
        <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
          Reference pages
          <span className="ml-2 text-xs text-[#484f58]">({refPages.length})</span>
        </h2>
        <Card>
          {refPages.length === 0 ? (
            <p className="text-xs text-[#484f58] py-4 text-center">
              Add pages whose content style you want to emulate. We'll analyze their reels and surface 100+ similar 500K+ view reels.
            </p>
          ) : (
            <div className="space-y-2">
              {refPages.map((p) => (
                <div key={p.id} className="flex items-center justify-between p-3 bg-[#0d1117] rounded-lg">
                  <div>
                    <span className="text-sm font-medium text-[#e6edf3]">@{p.ig_username}</span>
                    {p.niche && <span className="ml-2 text-xs text-[#484f58]">{p.niche}</span>}
                  </div>
                  <Button size="sm" variant="danger" onClick={() => handleRemove(p.id)} loading={removingId === p.id}>
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* ManyChat Integration */}
      <div>
        <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
          Integrations
        </h2>
        <Card>
          <div className="space-y-4">
            <div className="p-4 rounded-xl border border-[#1b2028] bg-gradient-to-r from-[#0d1117] to-[#0d1117] relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-r from-[#2B54E1]/5 via-transparent to-[#2B54E1]/5 pointer-events-none" />
              <div className="relative flex items-center gap-2 mb-2">
                <div className="w-6 h-6 rounded bg-[#2B54E1] flex items-center justify-center">
                  <span className="text-[8px] font-bold text-white">MC</span>
                </div>
                <span className="text-sm font-medium text-[#e6edf3]">ManyChat</span>
                {manychatKey ? (
                  <span className="text-[10px] text-[#3fb950] bg-[#3fb950]/10 px-1.5 py-0.5 rounded">Connected</span>
                ) : (
                  <span className="text-[10px] text-[#484f58] bg-[#21262d] px-1.5 py-0.5 rounded">Not connected</span>
                )}
              </div>
              <p className="relative text-[11px] text-[#484f58] mb-3">
                Connect your ManyChat account to track new leads and subscribers on your dashboard.
              </p>
              <div className="relative flex gap-2">
                <input
                  type="password"
                  placeholder="ManyChat API Key"
                  value={manychatKey}
                  onChange={(e) => setManychatKey(e.target.value)}
                  className="flex-1 h-9 px-3 text-sm bg-[#0d1117] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff]"
                />
                <Button onClick={handleSaveManychat} loading={savingManychat} disabled={!manychatKey.trim()}>
                  {manychatConnected ? "Update" : "Connect"}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
