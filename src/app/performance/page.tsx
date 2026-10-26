'use client';

import React from 'react';
import { DailyPerformanceDashboard } from '@/components/trading/DailyPerformanceDashboard';

export default function PerformancePage() {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <DailyPerformanceDashboard />
    </div>
  );
}
