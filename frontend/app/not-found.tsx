import { Compass } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex h-[70vh] flex-col items-center justify-center text-center">
      <Compass size={32} className="mb-4 text-slate-600" />
      <p className="text-lg font-semibold text-slate-200">Página no encontrada</p>
      <p className="mt-1 text-sm text-slate-500">Esta ruta no existe en el panel.</p>
      <Link href="/" className="btn-primary mt-5">
        Volver al dashboard
      </Link>
    </div>
  );
}
