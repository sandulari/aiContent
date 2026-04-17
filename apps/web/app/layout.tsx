import "@/app/globals.css";
import { Shell } from "@/components/layout/shell";

export const metadata = {
  title: "Shadow Pages",
  description: "Your content engine for Instagram theme pages",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head />
      <body className="bg-background text-text-primary" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
