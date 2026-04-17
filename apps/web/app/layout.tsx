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
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Roboto:wght@300;400;500;700;900&family=Open+Sans:wght@300;400;600;700;800&family=Lato:wght@300;400;700;900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-background text-text-primary" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
