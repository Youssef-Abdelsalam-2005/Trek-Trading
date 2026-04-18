import { Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Canvas from "./pages/Canvas";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="app">
      <nav className="app-nav" aria-label="Main navigation">
        <div className="app-nav__brand">Trek Trading</div>
        <ul className="app-nav__links">
          <li>
            <NavLink to="/" end>
              Dashboard
            </NavLink>
          </li>
          <li>
            <NavLink to="/settings">Settings</NavLink>
          </li>
        </ul>
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/experiments/:id" element={<Canvas />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  );
}
