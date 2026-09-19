import { defineConfig } from "vite";
import { ldrawPlugin } from "./server/ldraw";

export default defineConfig({
  plugins: [ldrawPlugin()],
  server: { host: "0.0.0.0" },
});
