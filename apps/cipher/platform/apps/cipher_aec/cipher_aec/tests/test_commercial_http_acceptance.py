"""Opt-in cookie/CSRF qualification against the existing isolated COM fixture.

No credential, cookie or CSRF value is retained in evidence or stdout.
"""
import copy
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPCookieProcessor
from uuid import uuid4


def run_http_acceptance(repository=None, base_url="http://127.0.0.1:18880"):
    from jsonschema import Draft202012Validator
    repository = Path(repository or Path.cwd())
    native = json.loads((repository / "apps/cipher/docs/framework/evidence/r1/commercial-native-acceptance.json").read_text())
    fixture = native["fixture"]
    company, user, alias = fixture["company"], fixture["user"], fixture["alias"]
    schema = json.loads((repository / "apps/cipher/platform/apps/cipher_aec/cipher_aec/commercial/schemas/api-v1.schema.json").read_text())
    response_types = {"pursuits":"ComPursuitList", "pursuit":"ComPursuit", "proposals":"ComProposalList", "proposal":"ComProposalDetail", "proposal_revision":"ComRevision", "compare_revisions":"ComComparison", "create_pursuit":"ComPursuitCommand", "update_pursuit":"ComPursuitCommand", "create_proposal":"ComProposalCommand", "save_proposal_revision":"ComProposalCommand"}
    validators = {key:Draft202012Validator({**schema,"$ref":"#/$defs/"+value}) for key,value in response_types.items()}
    password = secrets.token_urlsafe(32)
    docker = str(repository / "apps/cipher/platform/deployment/docker-local.sh")
    checks = []
    report = {"schema":"cipher.com01.http-acceptance.v1", "status":"running", "company":company, "user":user, "alias":alias, "project":None, "origin":base_url, "credentials_recorded":False, "checks":checks}
    def prepare(source_read=1, commercial_read=1, setup_password=False):
        args = [docker,"exec"]
        environment = os.environ.copy()
        if setup_password:
            environment["CIPHER_COM_HTTP_PASSWORD"] = password
            args += ["-e","CIPHER_COM_HTTP_PASSWORD"]
        args += ["-w","/home/frappe/frappe-bench","cipher-r0-runtime-1","bench","--site","cipher.localhost","execute","cipher_aec.tests.test_commercial_acceptance.prepare_http_fixture","--kwargs",json.dumps({"user":user,"alias":alias,"source_read":source_read,"commercial_read":commercial_read,"setup_password":int(setup_password)})]
        result = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=45, cwd=repository)
        if result.returncode:
            raise AssertionError("Isolated COM fixture setup failed; credentials and raw diagnostics withheld")
        return json.loads(result.stdout.strip().splitlines()[-1])
    class Session:
        def __init__(self):
            self.cookies=CookieJar();self.opener=build_opener(HTTPCookieProcessor(self.cookies));self.token=None
        def request(self,path,method="GET",payload=None,headers=None,form=False):
            headers={"Host":"cipher.localhost",**(headers or {})}
            if self.token and "X-Frappe-CSRF-Token" not in headers:
                headers["X-Frappe-CSRF-Token"]=self.token
            data=None
            if payload is not None:
                if form:
                    data=urlencode(payload).encode();headers["Content-Type"]="application/x-www-form-urlencoded"
                elif method=="GET":
                    path += "?" + urlencode(payload)
                else:
                    data=json.dumps(payload).encode();headers["Content-Type"]="application/json"
            request=Request(base_url+path,data=data,headers=headers,method=method)
            try:response=self.opener.open(request,timeout=25)
            except HTTPError as error:response=error
            with response:return response.status,json.loads(response.read())
        def login(self,account):
            status,_=self.request("/api/method/login","POST",{"usr":account,"pwd":password},form=True)
            assert status==200
            status,envelope=self.request("/api/method/cipher_aec.api.v1.session")
            assert status==200 and envelope["message"]["data"]["user"]==account
            data=envelope["message"]["data"]
            assert "project.read" not in data["capabilities"],"Company-only identity unexpectedly has Project capability"
            status,projects=self.request("/api/method/cipher_aec.api.v1.projects",payload={"company":company,"count_mode":"exact"})
            assert status==200 and projects["message"]["data"]["items"]==[] and projects["message"]["data"]["total"]==0
            self.token=data["csrf_token"]
            return data
        def close(self):
            if self.token:self.request("/api/method/logout","POST")
            self.cookies.clear()
    primary, secondary=Session(),Session()
    def rpc(session,name,payload,*,method="GET",expected=200,operation=None,csrf=True):
        headers={}
        if operation:headers["Idempotency-Key"]=operation
        if not csrf:headers["X-Frappe-CSRF-Token"]=""
        status,body=session.request("/api/method/cipher_aec.commercial.api."+name,method,payload,headers)
        envelope=body.get("message",{})
        assert status==expected,(name,status,expected,envelope.get("error",{}).get("code"))
        assert envelope.get("schema")=="cipher.api.v1" and isinstance(envelope.get("request_id"),str)
        if status==200:
            validators[name].validate(envelope["data"])
            assert "error" not in envelope
        else:assert "error" in envelope and "data" not in envelope
        checks.append({"route":"cipher_aec.commercial.api."+name,"method":method,"http_status":status,"error_code":envelope.get("error",{}).get("code"),"response_schema_validated":status==200,"csrf_header_sent":bool(csrf and session.token)})
        return envelope
    try:
        prepare(setup_password=True)
        primary.login(user);secondary.login(alias)
        report["company_only_session_without_project"]=True
        scope={"company":company}
        fields={"title":"HTTP synthetic authored pursuit","geography":"Isolated local fixture"}
        create={**scope,"party_type":"Customer","party_id":fixture["customer"],"fields":fields}
        rpc(primary,"create_pursuit",create,method="POST",expected=400,operation=str(uuid4()),csrf=False)
        pursuit_operation=str(uuid4())
        pursuit=rpc(primary,"create_pursuit",create,method="POST",operation=pursuit_operation)["data"]["pursuit"]
        same=rpc(secondary,"create_pursuit",create,method="POST",operation=pursuit_operation)["data"]
        assert same["operation"]["replayed"] and same["pursuit"]["id"]==pursuit["id"]
        detail=rpc(primary,"pursuit",{**scope,"pursuit_id":pursuit["id"]})["data"]
        assert detail["fields"]["title"]==fields["title"]
        revised_fields={**fields,"title":"HTTP updated synthetic authored pursuit"}
        updated=rpc(primary,"update_pursuit",{**scope,"pursuit_id":pursuit["id"],"expected_revision":1,"fields":revised_fields},method="POST",operation=str(uuid4()))["data"]["pursuit"]
        assert updated["revision_number"]==2 and updated["fields"]["title"]==revised_fields["title"]
        operation=str(uuid4())
        create_proposal={**scope,"pursuit_id":pursuit["id"],"composition":fixture["composition"]}
        first=rpc(primary,"create_proposal",create_proposal,method="POST",operation=operation)["data"]
        proposal,revision=first["proposal"],first["revision"]
        again=rpc(secondary,"create_proposal",create_proposal,method="POST",operation=operation)["data"]
        assert again["operation"]["replayed"] and again["revision"]["id"]==revision["id"]
        changed=copy.deepcopy(fixture["composition"])
        changed["terms"]="HTTP successor authored terms"
        changed["price_lines"].reverse()
        for row in changed["price_lines"]:row["selected"]=not row["selected"]
        save={**scope,"proposal_id":proposal["id"],"expected_revision":1,"expected_native_fingerprint":revision["native_fingerprint"],"composition":changed}
        second=rpc(primary,"save_proposal_revision",save,method="POST",operation=str(uuid4()))["data"]
        assert second["revision"]["pricing"]["total"]=="25.50"
        rpc(primary,"save_proposal_revision",save,method="POST",operation=str(uuid4()),expected=412)
        stale={**save,"expected_revision":2,"expected_native_fingerprint":"0"*64}
        rpc(primary,"save_proposal_revision",stale,method="POST",operation=str(uuid4()),expected=412)
        comparison=rpc(primary,"compare_revisions",{**scope,"proposal_id":proposal["id"],"left_revision":revision["id"],"right_revision":second["revision"]["id"]})["data"]
        assert comparison["changes"]["terms"]["changed"] and len(comparison["changes"]["price_lines"]["changed"])==2
        rpc(primary,"proposal_revision",{**scope,"revision_id":revision["id"]})
        rpc(primary,"proposal",{**scope,"proposal_id":proposal["id"]})
        rpc(primary,"pursuits",{**scope,"count_mode":"exact","limit":1})
        rpc(primary,"proposals",{**scope,"count_mode":"exact","limit":1})
        for doctype,identifier in (("Quotation",proposal["quotation"]),("Cipher Proposal Revision",revision["id"])):
            status,body=primary.request("/api/resource/"+quote(doctype,safe="")+"/"+quote(identifier,safe=""),"PUT",{"terms":"Attempted generic bypass"})
            assert status==403 and body["message"]["error"]["code"]=="route_unavailable"
            checks.append({"check":"native_or_immutable_generic_route_denied","doctype":doctype,"http_status":status})
        status,body=primary.request("/api/method/cipher_aec.api.company.history",payload={**scope,"count_mode":"exact"})
        assert status==200 and body["message"]["data"]["total"]>0
        prepare(source_read=0)
        status,body=primary.request("/api/method/cipher_aec.api.company.history",payload={**scope,"count_mode":"exact"})
        assert status==200 and body["message"]["data"]["items"]==[] and body["message"]["data"]["total"]==0 and body["message"]["data"]["next_cursor"] is None
        checks.append({"check":"current_native_party_revocation_hides_company_history_items_counts_cursor","http_status":status})
        rpc(primary,"proposal",{**scope,"proposal_id":proposal["id"]},expected=404)
        rpc(primary,"create_proposal",create_proposal,method="POST",operation=operation,expected=404)
        status,body=primary.request("/api/method/cipher_aec.api.company.operation",payload={**scope,"operation_id":operation})
        assert status==404 and "data" not in body["message"]
        checks.append({"check":"current_native_party_revocation_receipt_denied","http_status":status})
        prepare(commercial_read=0)
        rpc(primary,"proposal",{**scope,"proposal_id":proposal["id"]},expected=403)
        rpc(secondary,"create_proposal",create_proposal,method="POST",operation=operation,expected=403)
        status,body=secondary.request("/api/method/cipher_aec.api.company.operation",payload={**scope,"operation_id":operation})
        assert status==403 and "data" not in body["message"]
        checks.append({"check":"current_company_duty_revocation_receipt_denied","http_status":status})
        report.update(status="passed",pursuit_id=pursuit["id"],proposal_id=proposal["id"],current_revision=second["revision"]["id"],alias_replay_same_effect=True,scope_alternates_terms_preserved=True)
    finally:
        try:prepare()
        finally:primary.close();secondary.close()
    report["captured_at"]=datetime.now(timezone.utc).isoformat()
    report["qualification_limits"]=["Draft only; no issued output, send, award, posting or external provider effect.","Only isolated synthetic fixture roles/duties changed and restored.","Company document/estimate references remain typed unavailable pending their canonical extension."]
    return report


if __name__=="__main__":
    report=run_http_acceptance()
    path=Path("apps/cipher/docs/framework/evidence/r1/commercial-http-acceptance.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
