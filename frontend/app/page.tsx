import Link from "next/link";

export default function HomePage() {
  return (
    <main className="grid min-h-dvh place-items-center p-6">
      <section className="max-w-lg text-center">
        <p className="text-sm font-semibold tracking-[0.2em] text-blue-700">MENTORA</p>
        <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-950">Your whiteboard tutor, grounded in your room.</h1>
        <p className="mt-4 text-slate-600">Pick a room, then open a space to work in.</p>
        <Link className="mt-6 inline-block rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white" href="/rooms">
          My rooms
        </Link>
      </section>
    </main>
  );
}
