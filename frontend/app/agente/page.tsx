import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { ChatPanel } from "@/features/agent/ChatPanel";

export const metadata: Metadata = { title: "Agente" };

export default function AgentePage() {
  return (
    <div>
      <PageHeader
        title="Agente"
        description="Habla con el agente como si fueras un cliente. Mismo motor que atenderá llamadas por voz más adelante."
      />
      <ChatPanel />
    </div>
  );
}
