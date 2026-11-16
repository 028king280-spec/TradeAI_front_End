'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  TrendingUp,
  Activity,
  Layers,
  BarChart3,
  GitMerge,
  Gauge,
  Compass,
  Brain,
  Bell,
  Wallet,
  BookOpen,
  ShieldCheck,
  Sun,
  Moon,
  Radio,
  SlidersHorizontal,
  Eye,
} from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';

interface SidebarProps {
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  category?: 'core' | 'indices' | 'secondary';
}

const navItems: NavItem[] = [
  {
    label: 'Options Dashboard',
    href: '/',
    icon: Activity,
    badge: 'Live',
    category: 'core',
  },
  {
    label: 'NIFTY 50 Analysis',
    href: '/options/nifty',
    icon: TrendingUp,
    category: 'indices',
  },
  {
    label: 'SENSEX Analysis',
    href: '/options/sensex',
    icon: TrendingUp,
    category: 'indices',
  },
  {
    label: 'BANK NIFTY Analysis',
    href: '/options/banknifty',
    icon: TrendingUp,
    category: 'indices',
  },
  {
    label: 'Option Chain',
    href: '/option-chain',
    icon: Layers,
    badge: 'Greeks',
    category: 'core',
  },
  {
    label: 'Signal Performance',
    href: '/performance',
    icon: BarChart3,
    badge: 'Audit',
    category: 'core',
  },
  {
    label: 'Market Sentiment',
    href: '/sentiment',
    icon: Gauge,
    badge: 'Live',
    category: 'core',
  },
  {
    label: 'Chart Patterns',
    href: '/patterns',
    icon: GitMerge,
    category: 'core',
  },
  {
    label: "Today & Next Outlook",
    href: '/outlook',
    icon: Compass,
    category: 'core',
  },
  {
    label: 'AI Options Insights',
    href: '/ai-insights',
    icon: Brain,
    badge: 'Model',
    category: 'core',
  },
  {
    label: 'Paper Trading',
    href: '/paper-trading',
    icon: Wallet,
    category: 'secondary',
  },
  {
    label: 'Smart Alerts',
    href: '/alerts',
    icon: Bell,
    category: 'secondary',
  },
  {
    label: 'Deep Research',
    href: '/research',
    icon: BookOpen,
    badge: 'RAG',
    category: 'secondary',
  },
];

export const Sidebar: React.FC<SidebarProps> = ({ mobileOpen, onCloseMobile }) => {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 w-64 bg-[var(--bg-surface)] border-r border-[var(--border-subtle)] flex flex-col justify-between transition-transform duration-300 md:translate-x-0 shadow-sm ${
        mobileOpen ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      {/* Brand Header */}
      <div>
        <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3 group" onClick={onCloseMobile}>
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 via-indigo-500 to-sky-400 p-0.5 flex items-center justify-center shadow-md shadow-blue-500/20 group-hover:scale-105 transition-transform">
              <div className="w-full h-full bg-[var(--bg-surface)] rounded-[6px] flex items-center justify-center">
                <TrendingUp className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              </div>
            </div>
            <div>
              <span className="font-semibold tracking-tight text-[var(--text-primary)] text-sm block font-mono">
                AIVOLVE <span className="text-blue-600 dark:text-blue-400 font-bold">AI</span>
              </span>
              <span className="text-[10px] text-[var(--text-muted)] block tracking-wider uppercase font-medium">
                Quant Terminal
              </span>
            </div>
          </Link>
        </div>

        {/* Live Feed Pill */}
        <div className="px-3 pt-3 pb-1">
          <div className="px-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio className="w-3 h-3 text-emerald-500 animate-pulse" />
              <span className="text-[11px] font-mono font-medium text-[var(--text-secondary)]">NSE / BSE Feeds</span>
            </div>
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold tracking-wide">
              LIVE
            </span>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="p-3 space-y-1 max-h-[calc(100vh-210px)] overflow-y-auto">
          <div className="px-3 py-1 text-[10px] font-mono font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Live Options Intelligence
          </div>
          {navItems.map((item) => {
            const isActive =
              item.href === '/'
                ? pathname === '/'
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onCloseMobile}
                className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-blue-50 dark:bg-white/[0.08] text-blue-700 dark:text-white border border-blue-200 dark:border-white/[0.12] font-semibold shadow-sm'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-hover)]'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 ${
                      isActive ? 'text-blue-600 dark:text-blue-400' : 'text-[var(--text-muted)]'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span
                    className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
                      item.badge === 'Live'
                        ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/20'
                        : item.badge === 'AI RAG'
                        ? 'bg-amber-500/15 text-amber-600 dark:text-amber-300 border border-amber-500/20'
                        : 'bg-blue-500/15 text-blue-600 dark:text-blue-300 border border-blue-500/20'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Footer Area: Settings, Theme Toggle, User Profile */}
      <div className="p-3 border-t border-[var(--border-subtle)] space-y-2 bg-[var(--bg-surface)]">
        <div className="flex items-center justify-between px-2 py-1">
          <span className="text-[11px] text-[var(--text-muted)] flex items-center gap-1.5 font-mono">
            <ShieldCheck className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
            <span>Terminal v1.0 • Executive</span>
          </span>

          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="p-1.5 rounded-md hover:bg-[var(--bg-surface-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            {theme === 'dark' ? (
              <Sun className="w-3.5 h-3.5 text-amber-500" />
            ) : (
              <Moon className="w-3.5 h-3.5 text-blue-600" />
            )}
          </button>
        </div>

        {/* User Card */}
        <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 border border-blue-200 dark:border-blue-700 flex items-center justify-center font-bold text-[10px] text-blue-700 dark:text-blue-300 font-mono">
              AV
            </div>
            <div>
              <div className="text-xs font-medium text-[var(--text-primary)]">Aivolve Trader</div>
              <div className="text-[9px] text-[var(--text-muted)] font-mono">trade.aivolvetech.in</div>
            </div>
          </div>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
        </div>
      </div>
    </aside>
  );
};
