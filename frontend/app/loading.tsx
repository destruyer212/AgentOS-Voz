export default function Loading() {
  return (
    <div className="animate-pulse">
      <div className="mb-8">
        <div className="h-6 w-40 rounded bg-surface-800" />
        <div className="mt-2 h-4 w-64 rounded bg-surface-800" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl border border-surface-700 bg-surface-900" />
        ))}
      </div>
      <div className="mt-6 h-64 rounded-xl border border-surface-700 bg-surface-900" />
    </div>
  );
}
