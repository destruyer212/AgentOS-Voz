import { WifiOff } from "lucide-react";

export function ApiErrorNotice({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-accent-rose/30 bg-accent-rose/10 px-4 py-3.5 text-sm text-rose-200">
      <WifiOff size={18} className="mt-0.5 shrink-0 text-accent-rose" />
      <div>
        <p className="font-medium text-rose-100">No se pudo cargar la información</p>
        <p className="mt-0.5 text-rose-200/80">{message}</p>
      </div>
    </div>
  );
}
