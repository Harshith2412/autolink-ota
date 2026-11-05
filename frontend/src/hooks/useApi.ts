import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../services/api";

export interface Query<T> { data: T | undefined; error: ApiError | null; loading: boolean; reload: () => void }

// Minimal query hook: fetch on mount/key change, optional polling, stale-response guard.
export function useApi<T>(path: string | null, pollMs = 0): Query<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const mine = ++seq.current;
    api.get<T>(path).then(
      (d) => { if (mine === seq.current) { setData(d); setError(null); setLoading(false); } },
      (e: ApiError) => { if (mine === seq.current) { setError(e); setLoading(false); } },
    );
  }, [path]);
  useEffect(() => {
    setLoading(path !== null);
    setData(undefined);
    load();
    if (!pollMs || !path) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [path, pollMs, load]);
  return { data, error, loading, reload: load };
}
