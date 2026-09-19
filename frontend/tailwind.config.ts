import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // A 768px (el "md" default) el grid de 3 columnas (280+1fr+320=600px
      // fijos) todavía deja muy poco al panel de informe en celulares chicos
      // en landscape (ej. iPhone SE ~667px). 700px es el piso real donde el
      // panel del medio queda legible; por debajo, mejor tabs que 3
      // columnas aplastadas.
      screens: {
        wide: "700px",
      },
    },
  },
  plugins: [],
};

export default config;
