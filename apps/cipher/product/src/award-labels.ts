const abilities: Record<string, string> = {
  'project.read': 'View Project', 'project.write': 'Edit Project', 'task.create': 'Create tasks',
  'document.read': 'View documents', 'document.write': 'Upload documents', 'ricky.run': 'Use Ricky',
  'approval.request': 'Request approvals', 'approval.decide': 'Review approvals', 'approval.execute': 'Execute approvals',
  'estimate.read': 'View estimates', 'estimate.write': 'Edit estimates',
  'contract.read': 'View contract', 'contract.write': 'Edit contract', 'wbs.read': 'View WBS', 'budget.read': 'View budget',
};
// Presentation only: allowed values always come from the current server policy.
export const awardAbilityLabel = (ability: string) => abilities[ability] || ability;
