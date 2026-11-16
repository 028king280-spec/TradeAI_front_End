import {
  Activity, Bell, BookOpen, BrainCircuit, ChartCandlestick, Compass,
  Eye, Gauge, Layers, LayoutDashboard, Search, Wallet,
} from 'lucide-react';

export const navigation = [
  { label: 'Workspace', items: [
    { label: 'Overview', href: '/', icon: LayoutDashboard },
    { label: 'Index terminal', href: '/options/nifty', icon: ChartCandlestick },
    { label: 'Option chain', href: '/option-chain', icon: Layers },
    { label: 'Stock explorer', href: '/search', icon: Search },
    { label: 'Paper trading', href: '/paper-trading', icon: Wallet },
    { label: 'Performance', href: '/performance', icon: Activity },
  ] },
  { label: 'Intelligence', items: [
    { label: 'AI insights', href: '/ai-insights', icon: BrainCircuit },
    { label: 'Sentiment', href: '/sentiment', icon: Gauge },
    { label: 'Outlook', href: '/outlook', icon: Compass },
    { label: 'Patterns', href: '/patterns', icon: ChartCandlestick },
    { label: 'Research', href: '/research', icon: BookOpen },
  ] },
  { label: 'Monitor', items: [
    { label: 'Alerts', href: '/alerts', icon: Bell },
    { label: 'Observer', href: '/observer', icon: Eye },
  ] },
];

export function isNavigationActive(pathname: string, href: string) {
  if (href === '/options/nifty') return pathname.startsWith('/options/');
  if (href === '/search') return pathname === '/search' || pathname.startsWith('/stocks/');
  return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);
}

export function workspaceTitle(pathname: string) {
  if (pathname.startsWith('/stocks/')) return 'Stock analysis';
  return navigation.flatMap(section => section.items)
    .find(item => isNavigationActive(pathname, item.href))?.label || 'Workspace';
}
