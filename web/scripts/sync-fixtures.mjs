// Copies Lane B's frozen contract fixtures (../fixtures) into public/ so the
// app can fall back to them when the API is down (DEMO_SAFE / wifi off).
// Runs automatically before `dev` and `build`.
import fs from "node:fs/promises";
import path from "node:path";

const web = path.resolve(import.meta.dirname, "..");
const from = path.resolve(web, "../fixtures");
const to = path.join(web, "public/bricolage-fixtures");

try {
  const files = await fs.readdir(from);
  await fs.mkdir(to, { recursive: true });
  for (const f of files) await fs.copyFile(path.join(from, f), path.join(to, f));
  console.log(`synced ${files.length} Lane B fixtures -> public/bricolage-fixtures`);
} catch {
  console.log("no ../fixtures found; keeping existing public/bricolage-fixtures");
}
