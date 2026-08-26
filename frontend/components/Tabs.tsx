"use client";

import { useState, type ReactNode } from "react";

interface Tab {
  id: string;
  label: string;
  content: ReactNode;
}

export function Tabs({ tabs, defaultTab }: { tabs: Tab[]; defaultTab?: string }) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.id);

  return (
    <div>
      <div className="mb-5 inline-flex rounded-lg border border-surface-700 bg-surface-900 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActive(tab.id)}
            className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              active === tab.id ? "bg-brand-500 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div key={tab.id} className={tab.id === active ? "animate-fade-in" : "hidden"}>
          {tab.content}
        </div>
      ))}
    </div>
  );
}
