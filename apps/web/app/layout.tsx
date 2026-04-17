import "@/app/globals.css";
import { Shell } from "@/components/layout/shell";
import {
  Inter,
  Roboto,
  Open_Sans,
  Lato,
  Poppins,
  Montserrat,
  Oswald,
  Playfair_Display,
  Bebas_Neue,
  Raleway,
  Nunito,
  Anton,
  DM_Sans,
  Space_Grotesk,
  Outfit,
} from "next/font/google";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const roboto = Roboto({ weight: ["300", "400", "500", "700", "900"], subsets: ["latin"], variable: "--font-roboto", display: "swap" });
const openSans = Open_Sans({ subsets: ["latin"], variable: "--font-open-sans", display: "swap" });
const lato = Lato({ weight: ["300", "400", "700", "900"], subsets: ["latin"], variable: "--font-lato", display: "swap" });
const poppins = Poppins({ weight: ["300", "400", "500", "600", "700", "800", "900"], subsets: ["latin"], variable: "--font-poppins", display: "swap" });
const montserrat = Montserrat({ subsets: ["latin"], variable: "--font-montserrat", display: "swap" });
const oswald = Oswald({ subsets: ["latin"], variable: "--font-oswald", display: "swap" });
const playfairDisplay = Playfair_Display({ subsets: ["latin"], variable: "--font-playfair-display", display: "swap" });
const bebasNeue = Bebas_Neue({ weight: "400", subsets: ["latin"], variable: "--font-bebas-neue", display: "swap" });
const raleway = Raleway({ subsets: ["latin"], variable: "--font-raleway", display: "swap" });
const nunito = Nunito({ subsets: ["latin"], variable: "--font-nunito", display: "swap" });
const anton = Anton({ weight: "400", subsets: ["latin"], variable: "--font-anton", display: "swap" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans", display: "swap" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk", display: "swap" });
const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit", display: "swap" });

const fontVars = [
  inter, roboto, openSans, lato, poppins, montserrat, oswald,
  playfairDisplay, bebasNeue, raleway, nunito, anton, dmSans,
  spaceGrotesk, outfit,
].map((f) => f.variable).join(" ");

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
    <html lang="en" className={fontVars}>
      <body className="bg-background text-text-primary" style={{ fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
