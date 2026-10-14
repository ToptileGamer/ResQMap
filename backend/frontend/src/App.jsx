import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Zones from "./pages/Zones";
import ZoneDetail from "./pages/ZoneDetail";
import Sos from "./pages/Sos";
import RoutePlanner from "./pages/RoutePlanner";
import AerialAnalysis from "./pages/AerialAnalysis";
import RiskForecast from "./pages/RiskForecast";
import NotFound from "./pages/NotFound";
import ZoneMap from "./components/ZoneMap";
import LayerPanel from "./components/LayerPanel";


export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="zones" element={<Zones />} />
        <Route path="zones/:zoneId" element={<ZoneDetail />} />
        <Route path="sos" element={<Sos />} />
        <Route path="route" element={<RoutePlanner />} />
        <Route path="aerial" element={<AerialAnalysis />} />
        <Route path="risk" element={<RiskForecast />} />
        <Route path="404" element={<NotFound />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Route>
    </Routes>
  );
}
