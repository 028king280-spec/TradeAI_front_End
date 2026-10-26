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
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                const t = localStorage.getItem('aivolve-theme') || 'light';
                if (t === 'dark') {
                  document.documentElement.classList.remove('light');
                  document.documentElement.classList.add('dark');
                  document.documentElement.setAttribute('data-theme', 'dark');
                  document.documentElement.style.colorScheme = 'dark';
                } else {
                  document.documentElement.classList.remove('dark');
                  document.documentElement.classList.add('light');
                  document.documentElement.setAttribute('data-theme', 'light');
                  document.documentElement.style.colorScheme = 'light';
                }
              } catch(e) {}
            `,
          }}
        />
      </head>
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


