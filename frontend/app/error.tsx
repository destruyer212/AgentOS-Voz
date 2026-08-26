"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-[70vh] flex-col items-center justify-center text-center">
      <AlertTriangle size={32} className="mb-4 text-accent-rose" />
      <p className="text-lg font-semibold text-slate-200">Algo salió mal</p>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{error.message || "Error inesperado en el panel."}</p>
      <button type="button" onClick={reset} className="btn-primary mt-5">
        Reintentar
      </button>
    </div>
  );
}
