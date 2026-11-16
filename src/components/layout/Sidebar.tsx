'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, ArrowUpRight, Moon, ShieldCheck, Sun, X } from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';
import { isNavigationActive, navigation } from './navigation';
import styles from './Workspace.module.css';

interface SidebarProps {
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({ mobileOpen, onCloseMobile }: SidebarProps) {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.querySelector<HTMLElement>('a, button')?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onCloseMobile();
      if (event.key !== 'Tab') return;
      const controls = Array.from(ref.current?.querySelectorAll<HTMLElement>('a, button') || [])
        .filter(element => element.getClientRects().length > 0);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', handleKey);
    return () => {
      document.body.style.overflow = priorOverflow;
      document.removeEventListener('keydown', handleKey);
      previous?.focus();
    };
  }, [mobileOpen, onCloseMobile]);

  return <aside ref={ref} id="workspace-navigation" aria-label="Workspace sidebar" className={`${styles.sidebar} ${mobileOpen ? styles.sidebarOpen : ''}`}>
    <Link href="/" onClick={onCloseMobile} className={styles.brand}>
      <span className={styles.brandIcon}><Activity size={23}/></span>
      <span>AIVOLVE<span className={styles.brandSuffix}>TRADING INTELLIGENCE</span></span>
      <span className={styles.brandVersion}>/ 03</span>
    </Link>
    <div className={styles.workspacePicker}>
      <span className={styles.workspaceAvatar}>A</span>
      <span><b>Personal workspace</b><small>Paper trading environment</small></span>
      <ShieldCheck size={15}/>
      {mobileOpen && <button className={`${styles.iconButton} ${styles.mobileMenu}`} onClick={onCloseMobile} aria-label="Close navigation"><X size={17}/></button>}
    </div>
    <nav aria-label="Main navigation">
      {navigation.map(group => <div className={styles.navGroup} key={group.label}>
        <p>{group.label.toUpperCase()}</p>
        {group.items.map(item => {
          const active = isNavigationActive(pathname, item.href);
          return <Link key={item.href} href={item.href} onClick={onCloseMobile} aria-current={active ? 'page' : undefined} className={`${styles.navItem} ${active ? styles.navActive : ''}`}>
            <item.icon size={17}/><span>{item.label}</span>
            {item.label === 'AI insights' && <span className={styles.aiLabel}>AI</span>}
            {active && <span className={styles.activeDot}/>}
          </Link>;
        })}
      </div>)}
    </nav>
    <div className={styles.sidebarBottom}>
      <div className={styles.safeCard}><ShieldCheck size={18}/><b>Built around discipline.</b><p>Every good trade starts<br/>with a clear risk boundary.</p><Link href="/paper-trading" onClick={onCloseMobile} className="workspace-text-link">Your paper workspace <ArrowUpRight size={13}/></Link></div>
      <div className={styles.profile}>
        <span className={styles.profileAvatar}>AV</span><span><b>Aivolve Trader</b><small>Personal workspace</small></span>
        <button className={styles.iconButton} onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? <Sun size={17}/> : <Moon size={17}/>}</button>
      </div>
    </div>
  </aside>;
}
