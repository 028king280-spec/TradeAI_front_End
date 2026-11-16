import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ThemeProvider } from '@/context/ThemeContext';
import { PaperTradingProvider } from '@/context/PaperTradingContext';
import { AppShell } from '@/components/layout/AppShell';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: 'AIVOLVE Trading AI — AI-Powered Indian Market Analysis',
  description:
    'Institutional-grade Indian market analysis for NSE and BSE stocks. Probability-based trade setups, automated technical indicators, and transparent AI market outlooks.',
  keywords: [
    'NSE',
    'BSE',
    'Indian Stock Market',
    'Stock Analysis',
    'NIFTY 50',
    'BANK NIFTY',
    'AIVOLVE',
    'Trading AI',
    'Technical Analysis',
  ],
  authors: [{ name: 'AIVOLVE Tech', url: 'https://trade.aivolvetech.in' }],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="light">
      <body className={`${inter.className} ${inter.variable} antialiased selection:bg-blue-500/20 selection:text-blue-700`}>
        <ThemeProvider>
          <PaperTradingProvider>
            <AppShell>{children}</AppShell>
          </PaperTradingProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}


