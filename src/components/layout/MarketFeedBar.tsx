'use client';

import { ShieldCheck } from 'lucide-react';
import { feedLabel, useMarketFeed } from '@/context/MarketFeedContext';
import styles from './Workspace.module.css';

export function MarketFeedBar() {
  const feed = useMarketFeed();
  const live = feed.dataStatus === 'LIVE' || feed.dataStatus === 'VERIFIED_LIVE';
  return <div className={`${styles.previewStrip} workspace-feed-bar`} role="status" aria-live="polite">
    <span><span className={styles.dot} style={{ background: live ? 'var(--bullish)' : 'var(--neutral-caution)' }}/>{feedLabel(feed.dataStatus)}<b>·</b>{feed.marketStatus === 'OPEN' ? 'NSE session open' : feed.marketStatus === 'CLOSED' ? 'NSE session closed' : 'Session status unavailable'}{feed.provider && <span className="workspace-provider"> · {feed.provider}</span>}</span>
    <span><ShieldCheck size={12}/> Paper trading only</span>
  </div>;
}
