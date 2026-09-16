import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Radiologist_OS",
  description: "Copiloto de redacción de informes de diagnóstico por imágenes",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="bg-zinc-950 text-zinc-100 antialiased h-screen overflow-hidden">
        {children}
      </body>
    </html>
  );
}
