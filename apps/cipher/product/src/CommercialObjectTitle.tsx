import { forwardRef, useEffect, useState } from 'react';
import { ObjectPageTitle, type ObjectPageTitlePropTypes } from '@ui5/webcomponents-react';

// Keep the official ObjectPageTitle and its public expanded/snapped content slots.
// A full-width action row prevents long business titles losing their phone width.
export function businessTitle(title: string | undefined, fallback: string) {
  return !title?.trim() || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(title.trim()) ? fallback : title;
}

const CommercialObjectTitle = forwardRef<HTMLDivElement, ObjectPageTitlePropTypes>((props, ref) => {
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 599px)').matches);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 599px)'); const changed = () => setPhone(media.matches);
    media.addEventListener('change', changed); return () => media.removeEventListener('change', changed);
  }, []);
  return <ObjectPageTitle {...props} ref={ref} actionsBar={phone ? undefined : props.actionsBar} expandedContent={phone ? <>{props.expandedContent}{props.actionsBar}</> : props.expandedContent} snappedContent={phone ? <>{props.snappedContent}{props.actionsBar}</> : props.snappedContent} />;
});
CommercialObjectTitle.displayName = 'CommercialObjectTitle';
export default CommercialObjectTitle;
