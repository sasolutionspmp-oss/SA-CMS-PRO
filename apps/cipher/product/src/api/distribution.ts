import { rpc } from './client';
import type { DistProfiles, DistCreateInstructionRequest, DistCreateInstructionResponse, DistInstructionResponse, DistDispatchDetail, DistDispatchList, DistCancelRequest, DistCancelResponse, DistRecipientChoices, DistInstructionList } from './distribution.generated';
const prefix = 'cipher_aec.integrations.distribution_api.';
export const distribution = {
  choices: (company: string, issue_id: string, signal?: AbortSignal) => rpc<DistRecipientChoices>(prefix + 'recipient_choices', { company, issue_id }, false, signal),
  instructions: (company: string, issue_id: string, cursor?: string, signal?: AbortSignal) => rpc<DistInstructionList>(prefix + 'list_instructions', { company, issue_id, cursor, limit: 50, count_mode: 'none' }, false, signal),
  profiles: (company: string, signal?: AbortSignal) => rpc<DistProfiles>(prefix + 'profiles', { company }, false, signal),
  create: (input: DistCreateInstructionRequest) => rpc<DistCreateInstructionResponse>(prefix + 'create_instruction', { ...input }, true),
  instruction: (company: string, instruction_id: string, signal?: AbortSignal) => rpc<DistInstructionResponse>(prefix + 'get_instruction', { company, instruction_id }, false, signal),
  list: (company: string, issue_id: string, cursor?: string, signal?: AbortSignal) => rpc<DistDispatchList>(prefix + 'list_dispatches', { company, issue_id, cursor, limit: 50, count_mode: 'none' }, false, signal),
  dispatch: (company: string, dispatch_id: string, signal?: AbortSignal) => rpc<DistDispatchDetail>(prefix + 'get_dispatch', { company, dispatch_id }, false, signal),
  cancel: (input: DistCancelRequest) => rpc<DistCancelResponse>(prefix + 'cancel_dispatch', { ...input }, true),
};
