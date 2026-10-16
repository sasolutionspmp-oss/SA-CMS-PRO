import { MessageStrip } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { Failure } from './components';
import AwardPlanReview from './AwardPlanReview';
import type { AwardReviewBinding } from './award-governance';

export default function AwardApprovalReview({ binding }: { binding?: AwardReviewBinding }) {
  if (!binding) return <Failure error={new ApiError('The exact award plan and its source binding could not be verified. This action cannot be reviewed here.', 'INVALID_CONTRACT', 200)} />;
  return <section aria-label="Independent Project award review"><MessageStrip design="Information" hideCloseButton>This full award creates one Project, a draft Sales Order and contract, the accepted cost budget and only the explicit initial team. It does not submit a Sales Order, certify billing or send documents.</MessageStrip><AwardPlanReview plan={binding.plan} /></section>;
}
