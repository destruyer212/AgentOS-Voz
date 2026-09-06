import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { cookies } from "next/headers";
import { ActiveCallsProvider } from "@/components/ActiveCallsProvider";
import { IncomingCallToasts } from "@/components/IncomingCallToasts";
import { Sidebar } from "@/components/Sidebar";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth";
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

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const role = await verifySessionToken(cookieStore.get(SESSION_COOKIE)?.value);

  return (
    <html lang="es" className={`${sans.variable} ${mono.variable}`}>
      <body className="font-sans">
        {role ? (
          <ActiveCallsProvider>
            <div className="relative flex h-screen overflow-hidden">
              <div
                className="pointer-events-none fixed inset-0 z-0 opacity-80"
                aria-hidden
                style={{
                  background:
                    "linear-gradient(90deg, rgba(77,216,240,0.08), transparent 18%, transparent 82%, rgba(45,212,191,0.07)), linear-gradient(180deg, rgba(255,255,255,0.03), transparent 32%)",
                }}
              />
              <Sidebar role={role} />
              <main className="relative z-10 flex-1 overflow-y-auto">
                <div className="mx-auto max-w-[1500px] px-6 py-6 lg:px-8">{children}</div>
              </main>
            </div>
            <IncomingCallToasts />
          </ActiveCallsProvider>
        ) : (
          // Sin sesion valida: el middleware ya redirigio a /login para
          // cualquier otra ruta (ver middleware.ts), asi que si llegamos
          // aca sin rol es justo esa pantalla -- se muestra sin el menu
          // alrededor.
          children
        )}
      </body>
    </html>
  );
}
