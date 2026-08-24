import Link from "next/link";
import { notFound } from "next/navigation";
import { SpaceGrid } from "@/features/spaces/SpaceGrid";
import { getRoom } from "@/lib/spaces/rooms";

export default async function RoomPage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  const { roomId } = await params;
  const room = getRoom(roomId);

  if (!room) {
    notFound();
  }

  return (
    <main className="mx-auto min-h-dvh max-w-6xl p-5 sm:p-8">
      <header className="border-b border-slate-200 pb-6">
        <Link className="text-sm font-semibold text-blue-700" href="/rooms">
          ← My rooms
        </Link>
        <h1 className="mt-1 text-3xl font-bold text-slate-950">{room.name}</h1>
        <p className="mt-1 text-slate-600">{room.description}</p>
      </header>
      <SpaceGrid roomId={room.id} />
    </main>
  );
}
