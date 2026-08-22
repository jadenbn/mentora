"use client";

const actions = ["Mark", "Hint", "Explain", "I’m Stuck", "Select for AI", "Import problem"];

export function TutorControls() {
  return (
    <div className="flex flex-wrap gap-2" aria-describedby="tutor-unavailable">
      {actions.map((action) => (
        <button key={action} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-semibold text-slate-500" disabled>
          {action}
        </button>
      ))}
      <span id="tutor-unavailable" className="sr-only">Tutor actions and problem import are unavailable until the backend API contract is connected.</span>
    </div>
  );
}
