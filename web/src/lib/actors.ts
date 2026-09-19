import type { TapeActor } from "./bricolage";

// Actor colours are real LDraw colours, so anything built from them (the tape
// tower, the step feed) looks like actual bricks.
export const ACTOR_BRICK: Record<TapeActor, { brick: string; ink: string; label: string }> = {
  router: { brick: "#0055bf", ink: "#ffffff", label: "Router" },
  planner: { brick: "#4b0082", ink: "#ffffff", label: "Planner" },
  designer: { brick: "#00838f", ink: "#ffffff", label: "Designer" },
  builder: { brick: "#1e5aa8", ink: "#ffffff", label: "Builder" },
  critic: { brick: "#923978", ink: "#ffffff", label: "Critic" },
  inspector: { brick: "#c91a09", ink: "#ffffff", label: "Inspector" },
  repair: { brick: "#f2cd37", ink: "#1a1a1a", label: "Repair" },
  scribe: { brick: "#237841", ink: "#ffffff", label: "Scribe" },
};
