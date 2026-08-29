"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ActiveCallSummary } from "@/app/api/active-calls/route";

interface ActiveCallsContextValue {
  activeCalls: ActiveCallSummary[];
  incoming: ActiveCallSummary[];
  dismiss: (id: string) => void;
}

const ActiveCallsContext = createContext<ActiveCallsContextValue>({
  activeCalls: [],
  incoming: [],
  dismiss: () => {},
});

export function useActiveCalls() {
  return useContext(ActiveCallsContext);
}

const POLL_MS = 3500;
const TOAST_TTL_MS = 18000;

/**
 * Sondea /api/active-calls cada POLL_MS y detecta llamadas nuevas (ids que
 * no estaban en el sondeo anterior) para dispararlas como notificacion de
 * "llamada entrante". Vive una vez en el layout raiz -- Sidebar y el stack
 * de toasts leen del mismo contexto en vez de sondear cada uno por su lado.
 */
export function ActiveCallsProvider({ children }: { children: React.ReactNode }) {
  const [activeCalls, setActiveCalls] = useState<ActiveCallSummary[]>([]);
  const [incoming, setIncoming] = useState<ActiveCallSummary[]>([]);
  const knownIds = useRef<Set<string>>(new Set());
  const seeded = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch("/api/active-calls", { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const data = (await res.json()) as { active: ActiveCallSummary[] };
        if (cancelled) return;

        setActiveCalls(data.active);

        if (!seeded.current) {
          // Primera carga de la pestana: lo que ya estaba en curso no es
          // "entrante", solo lo registramos como conocido en silencio.
          data.active.forEach((c) => knownIds.current.add(c.id));
          seeded.current = true;
          return;
        }

        const fresh = data.active.filter((c) => !knownIds.current.has(c.id));
        if (fresh.length > 0) {
          fresh.forEach((c) => knownIds.current.add(c.id));
          setIncoming((prev) => [...fresh, ...prev].slice(0, 5));
          fresh.forEach((c) => {
            setTimeout(() => {
              setIncoming((prev) => prev.filter((t) => t.id !== c.id));
            }, TOAST_TTL_MS);
          });
        }

        const stillActive = new Set(data.active.map((c) => c.id));
        const toForget: string[] = [];
        knownIds.current.forEach((id) => {
          if (!stillActive.has(id)) toForget.push(id);
        });
        toForget.forEach((id) => knownIds.current.delete(id));
      } catch {
        // backend no disponible: no hay novedad que mostrar, seguimos sondeando
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  function dismiss(id: string) {
    setIncoming((prev) => prev.filter((t) => t.id !== id));
  }

  return (
    <ActiveCallsContext.Provider value={{ activeCalls, incoming, dismiss }}>
      {children}
    </ActiveCallsContext.Provider>
  );
}
