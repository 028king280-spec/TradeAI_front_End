'use client';

import React from 'react';
import { PageHeading } from '@/components/shared/PageHeading';
import { DailyPerformanceDashboard } from '@/components/trading/DailyPerformanceDashboard';

export default function PerformancePage() {
  return (
    <div className="space-y-6">
      <PageHeading title="Performance" description="Measure the process behind every outcome."/>
      <DailyPerformanceDashboard />
    </div>
  );
}
