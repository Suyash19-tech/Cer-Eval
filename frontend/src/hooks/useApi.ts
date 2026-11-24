"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/services/api";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => Promise<void>;
}

interface Snapshot<T> { path: string | null; data?: T; error?: ApiError }

/** GET with optional polling. `interval` may be a function of the latest data so polling stops when work is done. */
export function useApi<T>(path: string | null, interval?: number | ((d: T | undefined) => number | false)): ApiState<T> {
  const [snap, setSnap] = useState<Snapshot<T>>({ path: null });
  const intervalRef = useRef(interval);
  const latest = useRef<T | undefined>(undefined);
  useEffect(() => { intervalRef.current = interval; });

  const load = useCallback(async () => {
    if (path === null) return;
    try {
      const d = await api.get<T>(path);
      latest.current = d;
      setSnap({ path, data: d });
    } catch (e) {
      setSnap((s) => ({ path, data: s.path === path ? s.data : undefined, error: e instanceof ApiError ? e : new ApiError(0, "network", String(e)) }));
    }
  }, [path]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    latest.current = undefined;
    const tick = () => {
      const iv = intervalRef.current;
      const ms = typeof iv === "function" ? iv(latest.current) : iv;
      if (ms && alive) {
        timer = setTimeout(async () => {
          await load();
          if (alive) tick();
        }, ms);
      }
    };
    void load().then(() => { if (alive) tick(); });
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [path, load]);

  const current = snap.path === path;
  return { data: current ? snap.data : undefined, error: current ? snap.error : undefined, loading: path !== null && !current, reload: load };
}
