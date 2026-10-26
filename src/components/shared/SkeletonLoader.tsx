import React from 'react';

export const SkeletonBox: React.FC<{ className?: string }> = ({ className = 'h-4 w-full' }) => {
  return (
    <div
      className={`animate-pulse rounded bg-slate-800/60 relative overflow-hidden before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_1.8s_infinite] before:bg-gradient-to-r before:from-transparent before:via-slate-700/30 before:to-transparent ${className}`}
    />
  );
};

export const DashboardSkeleton: React.FC = () => {
  return (
    <div className="space-y-8 pb-10">
      {/* Top Header Skeleton */}
      <div className="flex justify-between items-center pb-4 border-b border-[#1e283d]">
        <div className="space-y-2">
          <SkeletonBox className="h-7 w-64" />
          <SkeletonBox className="h-4 w-48" />
        </div>
        <div className="flex gap-3">
          <SkeletonBox className="h-8 w-32" />
          <SkeletonBox className="h-8 w-44" />
        </div>
      </div>

      {/* 4 Cards Skeleton */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="card-terminal p-4 space-y-3">
            <div className="flex justify-between">
              <SkeletonBox className="h-4 w-20" />
              <SkeletonBox className="h-4 w-12" />
            </div>
            <SkeletonBox className="h-8 w-36" />
            <SkeletonBox className="h-10 w-full" />
            <div className="flex justify-between pt-2 border-t border-[#1e283d]">
              <SkeletonBox className="h-3 w-16" />
              <SkeletonBox className="h-3 w-16" />
            </div>
          </div>
        ))}
      </div>

      {/* Sentiment Skeleton */}
      <div className="card-terminal p-6 h-36">
        <div className="flex gap-6 items-center">
          <SkeletonBox className="w-20 h-20 rounded-full shrink-0" />
          <div className="flex-1 space-y-3">
            <SkeletonBox className="h-5 w-48" />
            <SkeletonBox className="h-3 w-full" />
            <SkeletonBox className="h-4 w-72" />
          </div>
        </div>
      </div>

      {/* Setups Skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-3">
          <SkeletonBox className="h-5 w-40" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="card-terminal p-4 space-y-3">
              <div className="flex justify-between">
                <SkeletonBox className="h-5 w-32" />
                <SkeletonBox className="h-5 w-16" />
              </div>
              <SkeletonBox className="h-12 w-full" />
            </div>
          ))}
        </div>
        <div className="space-y-3">
          <SkeletonBox className="h-5 w-40" />
          {[1, 2].map((i) => (
            <div key={i} className="card-terminal p-4 space-y-3">
              <div className="flex justify-between">
                <SkeletonBox className="h-5 w-32" />
                <SkeletonBox className="h-5 w-16" />
              </div>
              <SkeletonBox className="h-12 w-full" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
