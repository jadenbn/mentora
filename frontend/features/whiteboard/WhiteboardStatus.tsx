export function ThinkingPill() {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none mx-auto w-fit rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm backdrop-blur-sm"
      role="status"
    >
      Thinking
      <span aria-hidden="true" className="ml-1 inline-flex gap-0.5">
        <span className="animate-bounce [animation-delay:-0.2s] motion-reduce:animate-none">.</span>
        <span className="animate-bounce [animation-delay:-0.1s] motion-reduce:animate-none">.</span>
        <span className="animate-bounce motion-reduce:animate-none">.</span>
      </span>
    </div>
  );
}
