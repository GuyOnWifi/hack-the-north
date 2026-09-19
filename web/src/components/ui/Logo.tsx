import { APP_NAME } from "@/lib/brand";
import { IsoBrick } from "./IsoBrick";

/** Square badge (stands where the red corporate logo sits in the reference). */
export function LogoTile({ size = 64 }: { size?: number }) {
  return (
    <div className="grid place-items-center rounded-[6px]" style={{ width: size, height: size, background: "linear-gradient(180deg,#f5b200,#fccd01)", boxShadow: "inset 0 0 0 2px rgba(255,255,255,0.35)" }}>
      <IsoBrick w={2} d={2} h={3} color="#d90000" size={size * 0.72} />
    </div>
  );
}

/** Chunky orange wordmark with an extruded underside, like the BUILDER title. */
export function Wordmark({ size = 46 }: { size?: number }) {
  return (
    <div
      className="select-none font-[900] uppercase leading-none"
      style={{
        fontSize: size,
        letterSpacing: "-0.02em",
        color: "#ff5a1f",
        textShadow: "0 2px 0 #d8420f, 0 4px 0 #b8360a, 0 8px 18px rgba(0,0,0,0.45)",
      }}
    >
      {APP_NAME}
    </div>
  );
}
