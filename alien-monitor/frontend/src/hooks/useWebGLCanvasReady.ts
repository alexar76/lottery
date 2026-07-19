import { useEffect, useState } from 'react';

/** Detect blank WebGL canvas (common with broken post-FX or GPU drivers). */
export function useWebGLCanvasReady(active: boolean, recheckKey: string | number = 0) {
  const [ready, setReady] = useState<boolean | null>(null);

  useEffect(() => {
    if (!active) {
      setReady(null);
      return;
    }
    let cancelled = false;

    const probe = () => {
      const canvas = document.querySelector('canvas');
      if (!canvas || cancelled) return;
      const img = new Image();
      img.onload = () => {
        if (cancelled) return;
        const tmp = document.createElement('canvas');
        tmp.width = 96;
        tmp.height = 96;
        const ctx = tmp.getContext('2d');
        if (!ctx) {
          setReady(false);
          return;
        }
        ctx.drawImage(img, 0, 0, 96, 96);
        const data = ctx.getImageData(0, 0, 96, 96).data;
        let bright = 0;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i] + data[i + 1] + data[i + 2] > 48) bright += 1;
        }
        setReady(bright > 8);
      };
      img.onerror = () => !cancelled && setReady(false);
      try {
        img.src = canvas.toDataURL('image/png');
      } catch {
        setReady(false);
      }
    };

    const t1 = window.setTimeout(probe, 2500);
    const t2 = window.setTimeout(probe, 6000);
    return () => {
      cancelled = true;
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [active, recheckKey]);

  return ready;
}
