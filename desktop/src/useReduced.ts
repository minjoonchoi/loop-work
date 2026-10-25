import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
/** Motion's current hook snapshots the initial preference; subscribe for live OS changes. */
export function useLiveReducedMotion() {
  const initial = useReducedMotion();
  const [reduced, setReduced] = useState(!!initial);
  useEffect(() => {
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}
