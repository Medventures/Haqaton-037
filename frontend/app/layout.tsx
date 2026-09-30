import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "cyrillic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin", "cyrillic"],
});

export const metadata: Metadata = {
  title: "AqylRoute AI",
  description: "Единый межведомственный маршрут для ребёнка с РАС",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ru"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <main className="flex-1">{children}</main>
        <footer className="border-t px-4 py-3 text-center text-xs text-muted-foreground">
          Сервис не ставит диагнозов и не заменяет консультацию специалиста. Данные в демо
          синтетические.
        </footer>
      </body>
    </html>
  );
}
