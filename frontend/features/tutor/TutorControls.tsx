const actions = ["Mark", "Hint", "Explain", "I’m Stuck", "Select for AI"];

export function TutorControls() {
  return (
    <div className="flex flex-wrap justify-end gap-2" aria-describedby="tutor-unavailable">
      {actions.map((action) => (
        <button key={action} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-semibold text-slate-500" disabled>
          {action}
        </button>
      ))}
      <span id="tutor-unavailable" className="sr-only">Tutor actions are unavailable until the backend API contract is connected.</span>
    </div>
  );
}
