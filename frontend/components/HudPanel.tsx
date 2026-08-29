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
      className={`relative border border-surface-700 bg-surface-900/90 backdrop-blur-sm ${
        glow ? "shadow-hud" : "shadow-panel"
      } ${className}`}
      style={{
        clipPath:
          "polygon(0 12px, 12px 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%)",
      }}
    >
      <span className="pointer-events-none absolute left-0 top-0 h-px w-3 bg-hud-400/70" />
      <span className="pointer-events-none absolute left-0 top-0 h-3 w-px bg-hud-400/70" />
      <span className="pointer-events-none absolute bottom-0 right-0 h-px w-3 bg-hud-400/70" />
      <span className="pointer-events-none absolute bottom-0 right-0 h-3 w-px bg-hud-400/70" />
      {children}
    </As>
  );
}
