import type { ReactNode } from "react";

/**
 * Panel con esquinas cortadas y borde con glow -- el "chrome" visual tipo
 * HUD/consola de operaciones que se repite en dashboard, llamadas, etc.
 * Envoltorio puro: no lleva logica, solo el marco.
 */
export function HudPanel({
  children,
  className = "",
  glow = false,
  as: As = "div",
}: {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  as?: "div" | "section";
}) {
  return (
    <As
      className={`relative overflow-hidden border border-hud-500/20 bg-surface-900/70 backdrop-blur-md ${
        glow ? "shadow-hud" : "shadow-panel"
      } ${className}`}
      style={{
        clipPath:
          "polygon(0 12px, 12px 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%)",
      }}
    >
      <span className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-hud-400/70 to-transparent" />
      <span className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-hud-500/20 to-transparent" />
      <span className="pointer-events-none absolute left-0 top-0 h-px w-5 bg-hud-300" />
      <span className="pointer-events-none absolute left-0 top-0 h-5 w-px bg-hud-300" />
      <span className="pointer-events-none absolute bottom-0 right-0 h-px w-5 bg-hud-300" />
      <span className="pointer-events-none absolute bottom-0 right-0 h-5 w-px bg-hud-300" />
      <span className="hud-scanline pointer-events-none absolute inset-x-0 top-0 h-1/2 opacity-40" />
      <div className="relative">{children}</div>
    </As>
  );
}
