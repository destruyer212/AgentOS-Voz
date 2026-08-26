"use client";

import { Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";

export function SearchInput({ placeholder }: { placeholder: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [value, setValue] = useState(searchParams.get("q") ?? "");
  const [isPending, startTransition] = useTransition();

  function updateQuery(nextValue: string) {
    setValue(nextValue);
    const params = new URLSearchParams(searchParams.toString());
    if (nextValue) {
      params.set("q", nextValue);
    } else {
      params.delete("q");
    }
    startTransition(() => {
      router.replace(`${pathname}?${params.toString()}`);
    });
  }

  return (
    <div className="relative w-full max-w-xs">
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
      <input
        value={value}
        onChange={(e) => updateQuery(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-surface-700 bg-surface-900 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder:text-slate-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      {isPending && (
        <span className="absolute right-3 top-1/2 h-1.5 w-1.5 -translate-y-1/2 animate-pulse rounded-full bg-brand-400" />
      )}
    </div>
  );
}
