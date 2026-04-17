"use client";

import { useEffect, useRef, useCallback } from "react";

export function usePolling(
  fn: () => void | Promise<void>,
  interval: number,
  enabled: boolean = true,
): void {
  const savedFn = useRef(fn);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    savedFn.current = fn;
  }, [fn]);

  const tick = useCallback(async () => {
    if (!enabled) return;
    try {
      await savedFn.current();
    } catch {
      // swallow errors to keep polling alive
    }
    if (enabled) {
      timeoutRef.current = setTimeout(tick, interval);
    }
  }, [interval, enabled]);

  useEffect(() => {
    if (!enabled) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      return;
    }

    // Run immediately, then schedule
    tick();

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [tick, enabled]);
}
