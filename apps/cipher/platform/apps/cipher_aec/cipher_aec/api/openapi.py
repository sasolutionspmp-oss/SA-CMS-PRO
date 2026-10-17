"""Deterministic OpenAPI 3.1 artifact from the fixed route catalog and schemas.

Run `python -m cipher_aec.api.openapi --check` in CI, or without --check to
regenerate. Does not import Frappe or contact a site. Signatures are parsed from
source AST so a parameter or HTTP method drift fails validation.
"""
import ast
import copy
import json
from pathlib import Path
import sys

from .catalog import ROUTES
from cipher_aec.governance.domain_approvals import ACTIONS as APPROVAL_ACTIONS
from cipher_aec.migrations.contracts import MAX_RECORDS, MAX_JSON_BYTES, NATIVE_DOCTYPES, DIMENSIONS

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"


def _object(properties, required=None, additional=False):
    return {"type":"object","properties":properties,"required":list(properties) if required is None else required,"additionalProperties":additional}


def _ref(name):
    return {"$ref":"#/components/schemas/"+name}


def _rewrite(value):
    if isinstance(value,dict):
        return {key:(item.replace("#/$defs/","#/components/schemas/") if key=="$ref" else _rewrite(item)) for key,item in value.items()}
    if isinstance(value,list):return [_rewrite(item) for item in value]
    return value


def _signature(identifier):
    module,name=identifier.rsplit(".",1)
    path=ROOT.joinpath(*module.split(".")[1:]).with_suffix(".py")
    tree=ast.parse(path.read_text())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
    decorators=[node for node in function.decorator_list if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="endpoint"]
    if len(decorators)!=1:raise ValueError("Missing endpoint decorator: "+identifier)
    methods=next((ast.literal_eval(kw.value) for kw in decorators[0].keywords if kw.arg=="methods"),["GET"])
    if methods != [ROUTES[identifier].method]:raise ValueError("Catalog method drift: "+identifier)
    args=function.args.args
    defaults={arg.arg:default for arg,default in zip(args[len(args)-len(function.args.defaults):],function.args.defaults)} if function.args.defaults else {}
    return [(arg.arg,arg.arg not in defaults,ast.literal_eval(defaults[arg.arg]) if arg.arg in defaults else None) for arg in args]


def _parameter(name, default, schemas):
    strings={"company","project","document_id","revision_id","packet_id","run_id","proposal_id","filename","title","sha256","query","question","subject","description","reason","excerpt_sha256","expected_version","manifest_hash","dataset_id","subject_id","currency","unit_id","dimension"}
    if name=="operation_id":return {"type":"string","format":"uuid","description":"Canonical UUIDv4; exactly equals Idempotency-Key."}
    if name=="manifest":return {"oneOf":[_ref("CanonicalManifest"),{"type":"string","maxLength":MAX_JSON_BYTES}]}
    if name=="references":return {"type":"array","maxItems":MAX_RECORDS,"items":_object({"id":{"type":"string","format":"uuid"},"kind":{"type":"string","enum":sorted(NATIVE_DOCTYPES)},"name":{"type":"string"},"unit_definition":_object({"dimension":{"type":"string","enum":sorted(DIMENSIONS)},"precision":{"type":"integer","minimum":0,"maximum":12}})},["id","kind","name"])}
    if name in {"unit_conversions","quantities"}:
        return copy.deepcopy(schemas["CanonicalManifest"]["properties"][name])
    if name=="limit":return {"type":"integer","minimum":1,"maximum":200,"default":default or 50}
    if name=="cursor":return {"type":["string","null"],"maxLength":4096,"description":"Signed, expiring cursor bound to current user, scope and duties."}
    if name=="count_mode":return {"type":"string","enum":["none","exact"],"default":"none"}
    if name in {"page","expected_revision","proposal_version","byte_length"}:return {"type":"integer","minimum":0 if name in {"expected_revision","byte_length"} else 1}
    if name=="status":return {"type":"string","enum":["Open","On hold","Completed","Cancelled"]}
    if name=="action":return {"type":"string","enum":sorted(action for action,spec in APPROVAL_ACTIONS.items() if spec.enabled)}
    if name=="party_type":return {"type":"string","enum":["Customer","Lead"]}
    if name=="decision":return {"type":"string","enum":["Grant","Reject"]}
    if name=="content_base64":return {"type":"string","contentEncoding":"base64","maxLength":13981016}
    if name in strings:return {"type":"string"}
    raise ValueError("Unspecified request schema: "+name)


def generate():
    source=json.loads((API/"schema.json").read_text())
    schemas=_rewrite(source["$defs"])
    # Embed one schema in the OpenAPI root resource; strip its external $id
    # before rewriting local definitions to the component location.
    canonical=json.loads((ROOT/"migrations/schemas/canonical-v1.schema.json").read_text())
    canonical.pop("$id", None)
    def canonical_refs(value):
        if isinstance(value,dict):
            return {k:(v.replace("#/$defs/","#/components/schemas/CanonicalManifest/$defs/") if k=="$ref" else canonical_refs(v)) for k,v in value.items()}
        if isinstance(value,list): return [canonical_refs(v) for v in value]
        return value
    schemas["CanonicalManifest"]=canonical_refs(canonical)
    extra=json.loads((API/"domain-schemas.json").read_text())
    schemas.update(_rewrite(extra))
    migration_responses=json.loads((ROOT/"migrations/schemas/canonical-api-v1.schema.json").read_text())
    def response_refs(value):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                if key=="$ref":
                    if item=="canonical-v1.schema.json": item="#/components/schemas/CanonicalManifest"
                    elif item.startswith("#/$defs/"): item=item.replace("#/$defs/","#/components/schemas/")
                    else: raise ValueError("Unrecognized canonical response reference: "+item)
                    result[key]=item
                else: result[key]=response_refs(item)
            return result
        if isinstance(value,list):return [response_refs(v) for v in value]
        return value
    schemas.update(response_refs(migration_responses["$defs"]))
    estimating=json.loads((ROOT/"estimating/schemas/api-v1.schema.json").read_text())
    schemas.update(_rewrite(estimating["$defs"]))
    est_requests={"register_unit":"RegisterUnitRequest","create_conversion":"CreateConversionRequest","create_rate":"CreateRateRequest","create_assembly":"CreateAssemblyRequest","create_estimate":"CreateEstimateRequest","calculate_revision":"CalculateRevisionRequest","get_record":"GetEstimateRecordRequest","list_records":"ListEstimateRecordsRequest","list_units":"ListEstimateUnitsRequest","list_acceptances":"ListEstimateAcceptancesRequest","acceptance_subject":"EstimateAcceptanceSubjectRequest"}
    typed_requests = {"cipher_aec.estimating.api": est_requests, "cipher_aec.api.masters":{"parties":"NativePartiesRequest","price_lists":"NativePriceListsRequest","units":"NativeUnitsRequest","currencies":"NativeCurrenciesRequest","items":"NativeItemsRequest","cost_centers":"NativeCostCentersRequest","accounts":"NativeAccountsRequest","award_items":"NativeAwardItemsRequest"}}
    for module, filename, requests in (
        ("cipher_aec.ricky.company_draft_save_api", "ricky/schemas/company-draft-save-api-v1.schema.json", {"draft_save_subject":"CompanyDraftSaveSubjectRequest", "save_draft":"CompanyDraftSaveRequest"}),
        ("cipher_aec.ricky.company_proposal_api", "ricky/schemas/company-proposal-api-v1.schema.json", {"start_proposal":"CompanyRickyProposalStartRequest", "get_run":"CompanyRickyProposalGetRunRequest", "run_events":"CompanyRickyProposalGetRunRequest", "get_proposal":"CompanyRickyProposalGetRequest", "cancel_run":"CompanyRickyProposalStopRequest"}),
        ("cipher_aec.ricky.company_api", "ricky/schemas/company-api-v1.schema.json", {"start_read":"CompanyRickyStartReadRequest", "get_run":"CompanyRickyGetRunRequest", "run_events":"CompanyRickyRunEventsRequest", "cancel_run":"CompanyRickyCancelRunRequest"}),
        ("cipher_aec.estimating.company_api", "estimating/schemas/api-company-v2.schema.json", {**{name:"Company"+request for name,request in est_requests.items()}, "accepted_baseline_reference":"CompanyAcceptedBaselineReferenceRequest"}),
        ("cipher_aec.takeoff.company_api", "takeoff/schemas/api-company-v2.schema.json", {"create_set":"CompanyTakeoffCreateSetRequest", "create_calibration":"CompanyTakeoffCreateCalibrationRequest", "create_measurement":"CompanyTakeoffCreateMeasurementRequest", "bind_line":"CompanyTakeoffBindLineRequest", "get_record":"CompanyTakeoffGetRequest", "list_records":"CompanyTakeoffListRequest", "drawing_impact":"CompanyTakeoffImpactRequest", "compare_measurements":"CompanyTakeoffCompareRequest"}),
        ("cipher_aec.documents.company_api", "documents/schemas/company-api-v1.schema.json", {"upload_document":"CompanyDocumentUploadRequest","list_documents":"CompanyDocumentListRequest","get_document":"CompanyDocumentDetailRequest","preview_revision":"CompanyDocumentPreviewRequest","search_documents":"CompanyDocumentSearchRequest","download_revision":"CompanyDocumentDownloadRequest","get_citation":"CompanyCitationRequest"}),
        ("cipher_aec.takeoff.api", "takeoff/schemas/api-v1.schema.json", {"create_set":"TakeoffCreateSetRequest", "create_calibration":"TakeoffCreateCalibrationRequest", "create_measurement":"TakeoffCreateMeasurementRequest", "bind_line":"TakeoffBindLineRequest", "get_record":"TakeoffGetRequest", "list_records":"TakeoffListRequest", "drawing_impact":"TakeoffImpactRequest", "compare_measurements":"TakeoffCompareRequest"}),
        ("cipher_aec.commercial.api", "commercial/schemas/api-v1.schema.json", {"pursuits":"ComPursuitsRequest", "pursuit":"ComPursuitRequest", "proposals":"ComProposalsRequest", "proposal":"ComProposalRequest", "proposal_revision":"ComRevisionRequest", "compare_revisions":"ComCompareRequest", "create_pursuit":"ComCreatePursuitRequest", "update_pursuit":"ComUpdatePursuitRequest", "create_proposal":"ComCreateProposalRequest", "save_proposal_revision":"ComSaveRevisionRequest","prepare_proposal_output":"ComPrepareOutputRequest","prepared_output":"ComPreparedOutputRequest","proposal_output_subject":"ComOutputSubjectRequest","issue":"ComIssueRequest","issues":"ComIssuesRequest"}),
        ("cipher_aec.construction_finance.api", "construction_finance/schemas/api-v1.schema.json", {"create_contract":"CreateContractRequest", "author_revision":"AuthorContractRevisionRequest", "get_record":"GetContractRecordRequest", "list_contracts":"ListContractsRequest"}),
        ("cipher_aec.integrations.distribution_api", "integrations/schemas/distribution-v1.schema.json", {"create_instruction":"DistCreateInstructionRequest", "get_instruction":"DistGetInstructionRequest", "get_dispatch":"DistGetDispatchRequest", "get_recipient_delivery":"DistGetRecipientRequest", "list_dispatches":"DistListDispatchesRequest", "cancel_dispatch":"DistCancelRequest", "profiles":"DistProfilesRequest", "recipient_choices":"DistRecipientChoicesRequest", "list_instructions":"DistListInstructionsRequest"}),
        ("cipher_aec.project_controls.company_api", "project_controls/schemas/api-v1.schema.json", {"create_master":"PcCreateMasterRequest", "revise_master":"PcReviseMasterRequest", "get_revision":"PcGetRevisionRequest", "list_masters":"PcListMastersRequest"}),
        ("cipher_aec.project_controls.api", "project_controls/schemas/api-v1.schema.json", {"get_record":"PcGetProjectRecordRequest", "list_records":"PcListProjectRecordsRequest"}),
        ("cipher_aec.awards.api", "awards/schemas/api-v1.schema.json", {"list_handoffs":"AwListHandoffsRequest", "get_handoff":"AwGetHandoffRequest", "get_plan":"AwGetPlanRequest", "approval_subject":"AwApprovalSubjectRequest", "delegation_policy":"AwDelegationPolicyRequest", "team_choices":"AwTeamChoicesRequest", "source_preview":"AwSourcePreviewRequest", "preview_plan":"AwPreviewPlanRequest", "create_handoff":"AwCreateHandoffRequest", "plan_handoff":"AwPlanHandoffRequest"}),
    ):
        domain = json.loads((ROOT/filename).read_text())
        for name, value in _rewrite(domain["$defs"]).items():
            if name in schemas and schemas[name] != value:
                raise ValueError("Conflicting shared domain schema: "+name)
            schemas[name] = value
        typed_requests[module] = requests
    error_body=_object({"message":_object({"schema":{"const":"cipher.api.v1"},"request_id":{"type":"string","format":"uuid"},"meta":_ref("Meta"),"error":_ref("Error")})})
    paths={}
    for identifier,route in sorted(ROUTES.items()):
        signature=_signature(identifier)
        # expected_version defaults to None to generate a useful 428; the API
        # contract still requires it for fresh optimistic commands.
        module, method_name = identifier.rsplit(".", 1)
        if module in typed_requests:
            request_schema=schemas[typed_requests[module][method_name]]
            properties=copy.deepcopy(request_schema["properties"])
            required=list(request_schema["required"])
            if set(properties)!={name for name,_,_ in signature}:
                raise ValueError("Domain request/signature drift: "+identifier)
        else:
            properties={name:_parameter(name,default,schemas) for name,required,default in signature}
            required=[name for name,is_required,default in signature if (is_required or name=="expected_version") and name!="operation_id"]
        if module in {"cipher_aec.api.approvals", "cipher_aec.api.company_approvals"} and "action" in properties:
            action_scope = "Company" if module.endswith("company_approvals") else "Project"
            properties["action"] = {"enum": sorted(action for action,spec in APPROVAL_ACTIONS.items() if spec.enabled and action_scope in spec.scopes)}
        if identifier in {"cipher_aec.documents.api.search_documents", "cipher_aec.documents.company_api.search_documents"}:
            properties["limit"]["maximum"]=20
        data=_ref(route.response)
        body=_object({"message":_object({"schema":{"const":"cipher.api.v1"},"request_id":{"type":"string","format":"uuid"},"meta":_ref("Meta"),"data":data})})
        operation={"operationId":identifier,"tags":[identifier.split(".")[-2]],"summary":identifier.rsplit(".",1)[1].replace("_"," "),"security":[{"frappeSession":[]}],"responses":{"200":{"description":"Authorized result; Frappe message envelope is normalized once by the client.","content":{"application/json":{"schema":body}}}}}
        if route.binary:
            operation["responses"]["200"]={"description":"Authorized source bytes as attachment; no JSON envelope.","headers":{"Content-Disposition":{"schema":{"type":"string"}},"X-Content-Type-Options":{"schema":{"const":"nosniff"}}},"content":{"application/octet-stream":{"schema":{"type":"string","format":"binary"}}}}
        if route.method=="GET":
            operation["parameters"]=[{"name":name,"in":"query","required":name in required,"schema":value} for name,value in properties.items()]
        else:
            operation["requestBody"]={"required":True,"content":{"application/json":{"schema":_object(properties,required)}}}
            operation["parameters"]=[{"name":"X-Frappe-CSRF-Token","in":"header","required":True,"schema":{"type":"string"},"description":"Session token obtained from the authorized session endpoint."}]
            if route.command:
                operation["parameters"].append({"name":"Idempotency-Key","in":"header","required":True,"schema":{"type":"string","format":"uuid"}})
                operation["x-idempotency-scope"]="canonical-person + UUIDv4; payload-bound, current rights checked before replay"
        for status,description in {401:"Missing or expired session",403:"Current authority denied",404:"Unavailable or out-of-scope resource",409:"Operation, lifecycle, manifest or grant conflict",412:"Stale source version",422:"Invalid input",428:"Required version/idempotency precondition missing",429:"Rate limit",503:"Retryable concurrency or quarantined/unavailable service"}.items():
            operation["responses"][str(status)]={"description":description,"content":{"application/json":{"schema":error_body}}}
        operation["responses"]["503"]["headers"]={"Retry-After":{"schema":{"type":"integer","minimum":1},"description":"Present for retryable database concurrency conflicts."}}
        paths["/api/method/"+identifier]={route.method.lower():operation}
    return {"openapi":"3.1.0","jsonSchemaDialect":"https://json-schema.org/draft/2020-12/schema","info":{"title":"Cipher AEC/CMS Pro API","version":"1.0.0","description":"Synthetic R0 supported RPC catalog. ERPNext/Frappe owns authentication and native masters. Financial submit/cancel and canonical import application are unqualified and unavailable."},"servers":[{"url":"/"}],"paths":paths,"components":{"securitySchemes":{"frappeSession":{"type":"apiKey","in":"cookie","name":"sid","description":"HttpOnly Frappe session cookie obtained by standard same-origin POST /api/method/login; use standard POST /api/method/logout to revoke. Authentication routes follow upstream Frappe contracts."}},"schemas":schemas}}


def main():
    result=json.dumps(generate(),indent=2,ensure_ascii=False)+"\n"
    target=API/"openapi.json"
    if "--check" in sys.argv:
        if not target.exists() or target.read_text()!=result:raise SystemExit("OpenAPI artifact differs; regenerate with python -m cipher_aec.api.openapi")
        print("OpenAPI catalog/schema/signature artifact matches")
    else:
        target.write_text(result);print("Wrote "+str(target))


if __name__=="__main__":main()
