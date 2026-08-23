import { useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

/**
 * True once hydrated. Lets a component tell "still on the server" apart from
 * "looked in localStorage and found nothing", without a setState-in-effect.
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}
