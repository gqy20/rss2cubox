'use client'

import { useEffect } from 'react'
import { gsap } from 'gsap'

type MotionMountProps = {
  scope: 'dashboard' | 'predictions'
}

export default function MotionMount({ scope }: MotionMountProps) {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const ctx = gsap.context(() => {
      if (scope === 'dashboard') {
        gsap.from('.dashboard-header, .briefing-status-strip, .briefing-hero-panel', {
          y: 12,
          duration: 0.46,
          ease: 'power3.out',
          stagger: 0.07,
        })
        gsap.from('.dashboard-right, .timeline .timeline-item', {
          y: 10,
          duration: 0.36,
          ease: 'power2.out',
          stagger: 0.035,
          delay: 0.08,
        })
      } else {
        gsap.from('.predictions-header, .prediction-lab-status, .predictions-main .pred-section, .prediction-review-pulse', {
          y: 12,
          duration: 0.44,
          ease: 'power3.out',
          stagger: 0.06,
        })
      }
    })

    return () => ctx.revert()
  }, [scope])

  return null
}
