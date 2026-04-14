import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ExperimentPage } from "./pages/ExperimentPage";
import "./App.css";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/experiments/:id" element={<ExperimentPage />} />
        <Route path="*" element={<Navigate to="/experiments/demo" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
