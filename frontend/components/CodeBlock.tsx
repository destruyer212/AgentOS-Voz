export function CodeBlock({ data }: { data: unknown }) {
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="max-h-72 overflow-auto rounded-lg border border-surface-700 bg-surface-950 p-3 font-mono text-xs leading-relaxed text-slate-400">
      {text}
    </pre>
  );
}
