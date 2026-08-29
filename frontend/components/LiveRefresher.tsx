"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Refresca la ruta actual (vuelve a correr el server component, trae datos
 * frescos del backend) cada `intervalMs` mientras `active` sea true. Pensado
 * para poder "ver" una llamada en curso avanzar en la pantalla sin recargar
 * a mano -- se detiene solo cuando la conversacion pasa a `closed`.
 */
export function LiveRefresher({ active, intervalMs = 2500 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs, router]);

  return null;
}
