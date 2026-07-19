import { useEffect, useState } from 'react';

const MQ = '(max-width: 767px)';

/** True when viewport is below Tailwind `md` (768px). */
export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(MQ).matches : false,
  );

  useEffect(() => {
    const mq = window.matchMedia(MQ);
    const onChange = () => setMobile(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return mobile;
}
