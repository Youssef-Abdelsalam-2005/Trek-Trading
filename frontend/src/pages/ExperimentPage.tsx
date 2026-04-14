import { useParams } from "react-router-dom";
import { AutoLoopPanel } from "../components/autoloop/AutoLoopPanel";
import { ExperimentLineageCanvas } from "../components/lineage";

export function ExperimentPage() {
  const { id } = useParams<{ id: string }>();

  if (!id) return null;

  return (
    <main style={{ maxWidth: "72rem", margin: "0 auto", padding: "2rem 1rem" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1.5rem", color: "#e0e0e0" }}>
        Experiment
      </h1>
      <section style={{ height: "600px", marginBottom: "2rem" }}>
        <ExperimentLineageCanvas experimentId={id} />
      </section>
      <AutoLoopPanel experimentId={id} />
    </main>
  );
}
