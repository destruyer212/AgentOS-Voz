import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: {
    default: "AgentOS Voz",
    template: "%s · AgentOS Voz",
  },
  description: "Panel de control para agentes de voz que ejecutan procesos empresariales reales.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${sans.variable} ${mono.variable}`}>
      <body className="font-sans">
        <div className="relative flex h-screen overflow-hidden">
          {/* Glow ambiental sutil, fijo, no interactivo -- da el aire "consola de operaciones" sin competir con el contenido. */}
          <div
            className="pointer-events-none fixed inset-0 z-0 opacity-60"
            aria-hidden
            style={{
              background:
                "radial-gradient(60rem 30rem at 15% -10%, rgba(109,109,247,0.10), transparent 60%), radial-gradient(50rem 26rem at 100% 10%, rgba(45,212,191,0.06), transparent 60%)",
            }}
          />
          <Sidebar />
          <main className="relative z-10 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
