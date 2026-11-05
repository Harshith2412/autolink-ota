import { useEffect, useState } from "react";

// Hash routing: "#/vehicles/VIN-1" -> ["vehicles", "VIN-1"]. Works from any static host.
export function useRoute(): string[] {
  const parse = () => (window.location.hash.replace(/^#\/?/, "").split("?")[0] || "fleet").split("/").map(decodeURIComponent);
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const href = (...parts: string[]) => "#/" + parts.map(encodeURIComponent).join("/");
export const navigate = (...parts: string[]) => { window.location.hash = href(...parts); };
