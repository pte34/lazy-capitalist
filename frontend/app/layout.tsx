import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Lazy Capitalist",
  description: "Let AI work. Let money flow.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
