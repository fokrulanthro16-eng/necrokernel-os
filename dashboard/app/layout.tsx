import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NecroKernel-OS Hypervisor",
  description: "Live process reanimation dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-mono antialiased">{children}</body>
    </html>
  );
}
