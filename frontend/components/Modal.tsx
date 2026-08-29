"use client";

import { X } from "lucide-react";
import { useEffect } from "react";
import type { ReactNode } from "react";

/**
 * Dialogo modal simple, sin dependencias externas. Usado para editar/
 * eliminar clientes y pedidos desde el panel -- cierra con Escape, click
 * afuera, o el boton X.
 */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-surface-950/80 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md animate-fade-in rounded-xl border border-hud-500/30 bg-surface-900 shadow-hud">
        <div className="flex items-center justify-between border-b border-surface-700 px-5 py-4">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Cerrar"
            className="rounded-md p-1 text-slate-500 transition-colors hover:bg-surface-800 hover:text-slate-200"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
