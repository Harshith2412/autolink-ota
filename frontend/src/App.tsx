import { useEffect, useState } from "react";
import { href, useRoute } from "./hooks/useRoute";
import { session } from "./services/api";
import type { User } from "./types/api";
import { Login } from "./pages/Login";
import { Fleet } from "./pages/Fleet";
import { VehicleDetail, Vehicles } from "./pages/Vehicles";
import { Firmware } from "./pages/Firmware";
import { CampaignDetail, Campaigns } from "./pages/Campaigns";
import { Audit, Diagnostics } from "./pages/Diagnostics";

const NAV: { id: string; label: string; admin?: boolean }[] = [
  { id: "fleet", label: "Fleet" }, { id: "vehicles", label: "Vehicles" }, { id: "firmware", label: "Firmware" },
  { id: "campaigns", label: "Campaigns" }, { id: "diagnostics", label: "Diagnostics" }, { id: "audit", label: "Audit log", admin: true },
];

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const route = useRoute();
  useEffect(() => session.onUnauthorized(() => { session.set(null); setUser(null); }), []);
  if (!user) return <Login onLogin={(t, u) => { session.set(t); setUser(u); }} />;
  const [page, id] = route;
  let content;
  switch (page) {
    case "vehicles": content = id ? <VehicleDetail id={id} /> : <Vehicles user={user} />; break;
    case "firmware": content = <Firmware user={user} />; break;
    case "campaigns": content = id ? <CampaignDetail id={id} user={user} /> : <Campaigns user={user} />; break;
    case "diagnostics": content = <Diagnostics />; break;
    case "audit": content = user.role === "admin" ? <Audit /> : <p className="note">The audit log is limited to administrators.</p>; break;
    default: content = <Fleet />;
  }
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <nav className="nav" aria-label="Main">
        <p className="wordmark">AutoLink OTA</p>
        <ul>
          {NAV.filter((n) => !n.admin || user.role === "admin").map((n) => (
            <li key={n.id}><a href={href(n.id)} aria-current={page === n.id || (n.id === "fleet" && !NAV.some((x) => x.id === page)) ? "page" : undefined}>{n.label}</a></li>
          ))}
        </ul>
        <div className="nav__user">
          <p>{user.username}<span className="muted"> {user.role}</span></p>
          <button className="btn btn--quiet" onClick={() => { session.set(null); setUser(null); }}>Sign out</button>
        </div>
      </nav>
      <main id="main" className="main" tabIndex={-1}>{content}</main>
    </div>
  );
}
