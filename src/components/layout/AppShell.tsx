'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { Sidebar } from './Sidebar';
import { TopHeader } from './TopHeader';
import { MarketFeedBar } from './MarketFeedBar';
import { DisclaimerBanner } from '../shared/DisclaimerBanner';
import { MarketFeedProvider } from '@/context/MarketFeedContext';
import { useTheme } from '@/context/ThemeContext';
import styles from './Workspace.module.css';

function LiveWorkspace({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme } = useTheme();
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  useEffect(() => {
    const media = window.matchMedia('(min-width: 761px)');
    const onResize = () => { if (media.matches) setMobileOpen(false); };
    media.addEventListener('change', onResize);
    return () => media.removeEventListener('change', onResize);
  }, []);

  return <MarketFeedProvider>
    <div className={`${styles.workspace} ${theme === 'light' ? styles.light : ''}`}>
      <a className="workspace-skip-link" href="#workspace-main">Skip to content</a>
      <Sidebar mobileOpen={mobileOpen} onCloseMobile={closeMobile}/>
      {mobileOpen && <button className={styles.backdrop} aria-label="Close navigation" onClick={closeMobile}/>}
      <div className={styles.main} inert={mobileOpen || undefined}>
        <TopHeader key={pathname} mobileOpen={mobileOpen} onToggleMobile={() => setMobileOpen(value => !value)}/>
        <MarketFeedBar/>
        <main id="workspace-main" className={`${styles.content} workspace-content`} tabIndex={-1}>{children}</main>
        <DisclaimerBanner/>
      </div>
    </div>
  </MarketFeedProvider>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === '/design-preview') return <>{children}</>;
  return <LiveWorkspace>{children}</LiveWorkspace>;
}
