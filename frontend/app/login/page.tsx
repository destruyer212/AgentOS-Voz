import { SignalHigh } from "lucide-react";
import type { Metadata } from "next";
import { LoginForm } from "@/features/auth/LoginForm";

export const metadata: Metadata = { title: "Ingresar" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-hud-500/20 bg-surface-900/80 p-6 shadow-hud backdrop-blur-xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center border border-hud-400/40 bg-hud-500/10 shadow-hud">
            <span className="absolute inset-1 border border-hud-300/20" />
            <SignalHigh size={19} className="relative text-hud-300" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">AgentOS Voz</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-hud-400/80">El Olivar Grill</p>
          </div>
        </div>
        <LoginForm next={next ?? ""} />
      </div>
    </div>
  );
}
