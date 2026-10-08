import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./components/Layout";
import VehicleCheck from "./pages/VehicleCheck";
import Browse from "./pages/Browse";
import Versions from "./pages/Versions";
import FamilyTimeline from "./pages/FamilyTimeline";
import Changes from "./pages/Changes";
import Search from "./pages/Search";
import DocumentDetail from "./pages/DocumentDetail";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<VehicleCheck />} />
          <Route path="browse" element={<Browse />} />
          <Route path="versions" element={<Versions />} />
          <Route path="versions/*" element={<FamilyTimeline />} />
          <Route path="changes" element={<Changes />} />
          <Route path="search" element={<Search />} />
          <Route path="doc/*" element={<DocumentDetail />} />
          <Route path="*" element={<p className="text-sm text-zinc-500">Page not found.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
