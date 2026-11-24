"use client";

import { useSyncExternalStore } from "react";
import { getReviewerToken, setReviewerToken } from "@/services/api";

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => { listeners.add(cb); return () => { listeners.delete(cb); }; };

/** The token lives in sessionStorage (cleared when the tab closes) and is only ever sent to our own backend. */
export function useReviewerToken(): [string, (t: string) => void] {
  const token = useSyncExternalStore(subscribe, getReviewerToken, () => "");
  return [token, (t) => { setReviewerToken(t); listeners.forEach((l) => l()); }];
}
