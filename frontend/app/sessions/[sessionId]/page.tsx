import Link from "next/link";
import { Whiteboard } from "@/features/whiteboard/Whiteboard";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;

  return (
    <main className="flex h-dvh flex-col bg-white">
      <header className="border-b border-slate-200 px-3 py-2 sm:px-5">
        <div className="min-w-0">
          <Link className="text-sm font-semibold text-blue-700" href="/">Mentora</Link>
          <p className="truncate text-sm text-slate-600">Whiteboard: {sessionId}</p>
        </div>
      </header>
      <section className="min-h-0 flex-1" aria-label="Whiteboard canvas">
        <Whiteboard />
      </section>
    </main>
  );
}
