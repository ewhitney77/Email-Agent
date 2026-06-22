import snapshot from "@/data/results.json";
import type { Snapshot } from "./types";
import Dashboard from "./Dashboard";

// Static import of the committed snapshot -> page is pre-rendered at build time.
// The GitHub Action refreshes data/results.json and Vercel redeploys.
export default function Page() {
  return <Dashboard data={snapshot as Snapshot} />;
}
