'use client';

import React, { useEffect, useState } from 'react';
import { useSpring } from 'framer-motion';

interface AnimatedNumberProps {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  className?: string;
}

export const AnimatedNumber: React.FC<AnimatedNumberProps> = ({
  value,
  prefix = '',
  suffix = '',
  decimals = 2,
  className = '',
}) => {
  const [displayValue, setDisplayValue] = useState(value);

  const spring = useSpring(0, {
    damping: 24,
    stiffness: 120,
  });

  useEffect(() => {
    spring.set(value);
  }, [spring, value]);

  useEffect(() => {
    return spring.on('change', (latest) => {
      setDisplayValue(Number(latest.toFixed(decimals)));
    });
  }, [spring, decimals]);

  // Format with commas for Indian notation where appropriate
  const formatted = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(displayValue);

  return (
    <span className={`tabular-nums inline-block tabular-nums ${className}`}>
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
};
