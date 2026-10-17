# C01 native-app protocol failure and correction candidate

The original real app run `3de147d4-8b4f-4703-8db9-7b466a05ac1e` failed with
`invalid_model_output: The local model returned malformed JSON.` It retained its
question/source progress and two initial retrieval tools, with no completed Task
effect. Root preserved the failed HTTP journal and native readback. They are not
rewritten, resumed with another question or presented as a passing journey.

The engine always supplies the three reviewed native tool schemas. The original
adapter omitted `format` whenever tools were present, so ordinary persisted runs
could not reach its constrained-answer branch. The prompt asked for JSON but did
not constrain the server's final content. The earlier no-tool host schema proof
therefore did not qualify this actual tools-present app path.

One authorized diagnostic probe loaded the original run `data_json` through a
read-only Frappe connection, followed by rollback/destroy. It reused the exact
question, two context entries and reviewed tool schemas against the same pinned
existing model. It used a new bounded diagnostic deadline without creating or
changing a run. Both inventory identity checks passed. In 73.859 seconds Ollama
returned 972 characters of plain prose, no native tool calls, `done:true` and
`done_reason:stop`. The old strict decoder refused it, reproducing the failure.
No tool, Task, setup or other database write was executed by the probe.

The safe summary is
`docs/framework/evidence/r3/ricky-local-ollama/c01-protocol-reproduction.json`
relative to the Cipher root. Raw request/response and source snapshot stay in
the operator's private `cipher-local/evidence-private/ricky-c01` folder. The
summary pins their hashes and the original adapter source hash without dumping
private run context or raw model text into the repository.

The official [native tool documentation](https://docs.ollama.com/capabilities/tool-calling)
and [structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs)
describe distinct modes. Upstream [issue 18944](https://github.com/ollama/ollama/issues/18944)
documents an interaction where JSON formatting prevents genuine tool calls;
[fix PR 18975](https://github.com/ollama/ollama/pull/18975) was still open when
checked October 17, 2026. Adding answer-only `format` beside native tools could
hide the required Task proposal capability, so the candidate does not depend on
that combination or change the model/server version.

The reviewed candidate uses at most two phases in one adapter generation:

1. Native tool selection sends the existing tools without `format`. A genuine
   native call passes the same complete-response, exact model, closed tool and
   typed argument validation before returning to the ordinary gateway. Mixed
   final answers and native calls remain refused.
2. If native selection returns no call, its content is provisional and is
   discarded. It is not delivered, parsed as tool intent, persisted as the answer
   or copied into the final prompt. A separate no-tools request synthesizes the
   final `answer`/`citations` from the original question and already verified
   context, using `format=ANSWER_SCHEMA` and grounding that schema in the prompt.
   Final synthesis has no permitted tools and cannot dispatch a call.

When an outer server-owned `task.propose` context entry already contains a
prepared proposal receipt, the adapter goes directly to constrained final
synthesis. This only removes available model tools. It does not approve/save the
draft, widen authority or parse receipt-looking JSON inside document excerpts.
The final prompt distinguishes a prepared draft from an actually saved Task.

One shared 150-second monotonic budget includes all identity checks and both
requests. Each socket/header/body remains bounded, and the final response is
fenced by another exact-name/digest check. No lease, queue or resource ceiling is
raised. The model's temperature/context/output/thread values remain unchanged.
Bounded `ModelResponse.sampling` now additionally records:

- `response_protocol: native-selection-then-schema-v1`
- `adapter_prompt_version: cipher-ollama-prompt-2`
- `model_requests`: actual one or two requests in this generation
- `phases`: actual native-selection and/or constrained-final phases

Tool/source/authority/citation/proposal checks remain in their existing services.
The model receives no new authority. Plain prose is still never accepted as a
final answer. Malformed calls, invalid final schema, unknown citations, expired
budgets or identity changes remain failures.

Three regression tests were observed failing against the prior implementation,
then passed with the candidate. Further focused checks cover nested untrusted
receipt text, final-phase tool injection and identity drift after synthesis.
All 25 adapter, five intent and 27 existing orchestration tests pass. An
independent read-only review checks the protocol/trust boundary. These are source
contract proofs; the candidate has not been called against a provider by this
lane. Root must build/install it and perform a fresh supervised native journey
with new operation IDs after confirming the old run remains terminal. Original
failed journals remain intact, and actual stored sampling requires root's native
read audit.
