"use client";

import { Check } from "lucide-react";

/**
 * A quiet confirmation that the canvas reached storage.
 *
 * Kept out of the way in the corner and aria-live polite: worth noticing if you
 * look for it, never worth interrupting a stroke for.
 */
export function SaveIndicator({ visible }: { visible: boolean }) {
  return (
    <div
      aria-live="polite"
      className={`pointer-events-none absolute bottom-4 right-4 z-40 flex items-center gap-1.5 rounded-full bg-slate-900/85 px-3 py-1.5 text-xs font-semibold text-white shadow-lg transition-opacity duration-500 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
    >
      <Check aria-hidden="true" className="size-3.5" strokeWidth={3} />
      {visible ? "Saved" : ""}
    </div>
  );
}
