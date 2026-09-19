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
