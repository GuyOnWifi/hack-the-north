export type ColourCode = number;

export interface BuildPart {
  part: string;
  colour: ColourCode;
  count: number;
  title: string;
}

export interface Build {
  id: string;
  file: string;
  model: string;
  name: string;
  theme: string;
  age: string;
  builders: string;
  tagline: string;
  pieces: number;
  parts: BuildPart[];
}

export type Confidence = "confident" | "review" | "unknown";

export interface InventoryItem {
  id: string;
  part: string;
  colour: ColourCode;
  title: string;
  count: number;
  status: Confidence;
  confidence: number;
  /** Normalised crop rectangle inside the captured photo. */
  crop: { x: number; y: number; w: number; h: number };
  alternatives: { part: string; colour: ColourCode; title: string; confidence: number }[];
}
