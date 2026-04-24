"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api, ApiError, ScheduledReel } from "@/lib/api";
import { ScheduleReelDialog } from "./ScheduleReelDialog";

interface Props {
  exportId: string;
  disabled?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
  onScheduled?: (row: ScheduledReel) => void;
}

/**
 * Button that opens the schedule dialog for a given export.
 * Before opening, checks that Instagram is connected + publishable.
 */
export function ScheduleButton({
  exportId,
  disabled,
  size = "sm",
  className,
  onScheduled,
}: Props) {
  const router = useRouter();
  const [checking, setChecking] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleClick = useCallback(async () => {
    if (disabled) return;
    setChecking(true);
    try {
      const status = await api.ig.status();
      if (!status.can_publish) {
        const msg = status.connected
          ? "Your Instagram account can't publish reels. Please reconnect or use a Business/Creator account."
          : "Connect Instagram first to schedule reels.";
        if (
          typeof window !== "undefined" &&
          window.confirm(`${msg}\n\nOpen Instagram settings?`)
        ) {
          router.push("/settings/instagram");
        }
        return;
      }
      setDialogOpen(true);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message || "Could not verify Instagram status."
          : "Could not verify Instagram status.";
      if (
        typeof window !== "undefined" &&
        window.confirm(`${msg}\n\nOpen Instagram settings?`)
      ) {
        router.push("/settings/instagram");
      }
    } finally {
      setChecking(false);
    }
  }, [disabled, router]);

  const handleSuccess = useCallback(
    (row: ScheduledReel) => {
      onScheduled?.(row);
    },
    [onScheduled],
  );

  return (
    <>
      <Button
        size={size}
        variant="secondary"
        onClick={handleClick}
        disabled={disabled || checking}
        loading={checking}
        className={className}
      >
        Schedule
      </Button>
      <ScheduleReelDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSuccess={handleSuccess}
        exportId={exportId}
      />
    </>
  );
}

export default ScheduleButton;
