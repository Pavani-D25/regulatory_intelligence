import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import PortalLayout from "./portal/PortalLayout";
import Dashboard from "./portal/pages/Dashboard";
import Regulations from "./portal/pages/Regulations";
import ChangeMonitor from "./portal/pages/ChangeMonitor";
import Compliance from "./portal/pages/Compliance";
import Impact from "./portal/pages/Impact";
import AskAI from "./portal/pages/AskAI";
import Reports from "./portal/pages/Reports";
import Alerts from "./portal/pages/Alerts";
import Admin from "./portal/pages/Admin";
import Team from "./portal/pages/Team";
import VehicleCheck from "./pages/VehicleCheck";
import Browse from "./pages/Browse";
import Versions from "./pages/Versions";
import FamilyTimeline from "./pages/FamilyTimeline";
import Search from "./pages/Search";
import DocumentDetail from "./pages/DocumentDetail";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<PortalLayout />}>
          {/* approved portal design (v2) */}
          <Route index element={<Dashboard />} />
          <Route path="regulations" element={<Regulations />} />
          <Route path="changes" element={<ChangeMonitor />} />
          <Route path="compliance" element={<Compliance />} />
          <Route path="impact" element={<Impact />} />
          <Route path="ai" element={<AskAI />} />
          <Route path="reports" element={<Reports />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="admin" element={<Admin />} />
          <Route path="team" element={<Team />} />
          {/* earlier RegTrack tools, kept inside the new shell */}
          <Route path="vehicle" element={<VehicleCheck />} />
          <Route path="browse" element={<Browse />} />
          <Route path="versions" element={<Versions />} />
          <Route path="versions/*" element={<FamilyTimeline />} />
          <Route path="search" element={<Search />} />
          <Route path="doc/*" element={<DocumentDetail />} />
          <Route path="*" element={<p className="empty">Page not found.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
