"""Finite reviewed native award dispatch catalog for the disabled action epoch.

This is a deployment prerequisite, not a sandbox or a source-code trust engine.
The fixed list covers target hook dispatch, native controller/MRO and the reviewed
callback/search/configuration entry points. It does not hash every transitive
business dependency. No values are learned or accepted from the running site.

Cipher hashes pin the explicitly reviewed disabled-action source bodies. An
enabled epoch requires a separately reviewed registry flag and matching pin.
No self-hash: updating this catalog is itself a reviewed deployment change.
Source hashes complement a coherent deployment/HUP; they do not prove that old
loaded Python equals subsequently changed disk. Configuration checks elsewhere
observe one transaction plus effective caches before insert, not a fence against
arbitrary concurrent administrator edits. No read/cleanup/config side effects.
"""
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path

import frappe
from cipher_aec.api.errors import DomainError

CATALOG = 'cipher.award.native.catalog.v1'
EXPECTED_APPS = ('frappe', 'erpnext', 'cipher_aec')
TARGETS = ('Project',
 'Sales Order',
 'Cipher Project Profile',
 'Cipher Construction Contract',
 'Cipher Budget Version',
 'Cipher Budget Line',
 'Cipher WBS Node',
 'Cipher Project Duty',
 'Cipher Award Adoption',
 'Cipher Award Line Adoption',
 'Cipher Award Handoff',
 'Cipher History Event',
 'Cipher Approval Consumption',
 'Cipher Command Receipt')
EXPECTED_EVENTS = {'Project': {'validate': ['cipher_aec.projects.guards.validate_project'],
             'on_trash': ['cipher_aec.projects.guards.prevent_delete']},
 'Sales Order': {'before_insert': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'before_validate': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'validate': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'before_save': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'before_submit': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'before_cancel': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'before_update_after_submit': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition'],
                 'on_trash': ['cipher_aec.governance.approvals.prevent_unsupported_financial_transition']},
 '*': {'on_update': ['frappe.desk.notifications.clear_doctype_notifications',
                     'frappe.workflow.doctype.workflow_action.workflow_action.process_workflow_actions',
                     'frappe.core.doctype.file.utils.attach_files_to_document',
                     'frappe.automation.doctype.assignment_rule.assignment_rule.apply',
                     'frappe.automation.doctype.assignment_rule.assignment_rule.update_due_date',
                     'frappe.core.doctype.user_type.user_type.apply_permissions_for_non_standard_user_type',
                     'frappe.core.doctype.permission_log.permission_log.make_perm_log',
                     'frappe.search.sqlite_search.update_doc_index'],
       'after_rename': ['frappe.desk.notifications.clear_doctype_notifications'],
       'on_cancel': ['frappe.desk.notifications.clear_doctype_notifications',
                     'frappe.workflow.doctype.workflow_action.workflow_action.process_workflow_actions',
                     'frappe.automation.doctype.assignment_rule.assignment_rule.apply'],
       'on_trash': ['frappe.desk.notifications.clear_doctype_notifications',
                    'frappe.workflow.doctype.workflow_action.workflow_action.process_workflow_actions',
                    'frappe.search.sqlite_search.delete_doc_index'],
       'on_update_after_submit': ['frappe.workflow.doctype.workflow_action.workflow_action.process_workflow_actions',
                                  'frappe.automation.doctype.assignment_rule.assignment_rule.apply',
                                  'frappe.automation.doctype.assignment_rule.assignment_rule.update_due_date',
                                  'frappe.core.doctype.file.utils.attach_files_to_document'],
       'on_change': ['frappe.automation.doctype.milestone_tracker.milestone_tracker.evaluate_milestone'],
       'after_delete': ['frappe.core.doctype.permission_log.permission_log.make_perm_log'],
       'validate': ['erpnext.support.doctype.service_level_agreement.service_level_agreement.apply',
                    'erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record.check_for_running_deletion_job']},
 'Cipher Project Profile': {},
 'Cipher Construction Contract': {},
 'Cipher Budget Version': {},
 'Cipher Budget Line': {},
 'Cipher WBS Node': {},
 'Cipher Project Duty': {},
 'Cipher Award Adoption': {},
 'Cipher Award Line Adoption': {},
 'Cipher Award Handoff': {},
 'Cipher History Event': {},
 'Cipher Approval Consumption': {},
 'Cipher Command Receipt': {}}

EXPECTED_MRO = {'Project': ['erpnext.projects.doctype.project.project.Project',
             'frappe.model.document.Document',
             'frappe.model.base_document.BaseDocument',
             'builtins.object'],
 'Sales Order': ['erpnext.selling.doctype.sales_order.sales_order.SalesOrder',
                 'erpnext.controllers.selling_controller.SellingController',
                 'erpnext.controllers.stock_controller.StockController',
                 'erpnext.controllers.accounts_controller.AccountsController',
                 'erpnext.utilities.transaction_base.TransactionBase',
                 'erpnext.controllers.status_updater.StatusUpdater',
                 'frappe.model.document.Document',
                 'frappe.model.base_document.BaseDocument',
                 'builtins.object'],
 'Cipher Project Profile': ['cipher_aec.cipher_awards.doctype.cipher_project_profile.cipher_project_profile.CipherProjectProfile',
                            'cipher_aec.awards.records.AwardRecord',
                            'frappe.model.document.Document',
                            'frappe.model.base_document.BaseDocument',
                            'builtins.object'],
 'Cipher Construction Contract': ['cipher_aec.cipher_finance.doctype.cipher_construction_contract.cipher_construction_contract.CipherConstructionContract',
                                  'cipher_aec.construction_finance.records.FinanceRecord',
                                  'frappe.model.document.Document',
                                  'frappe.model.base_document.BaseDocument',
                                  'builtins.object'],
 'Cipher Budget Version': ['cipher_aec.cipher_project_controls.doctype.cipher_budget_version.cipher_budget_version.CipherBudgetVersion',
                           'cipher_aec.project_controls.records.ProjectControlRecord',
                           'frappe.model.document.Document',
                           'frappe.model.base_document.BaseDocument',
                           'builtins.object'],
 'Cipher Budget Line': ['cipher_aec.cipher_project_controls.doctype.cipher_budget_line.cipher_budget_line.CipherBudgetLine',
                        'cipher_aec.project_controls.records.ProjectControlRecord',
                        'frappe.model.document.Document',
                        'frappe.model.base_document.BaseDocument',
                        'builtins.object'],
 'Cipher WBS Node': ['cipher_aec.cipher_project_controls.doctype.cipher_wbs_node.cipher_wbs_node.CipherWBSNode',
                     'cipher_aec.project_controls.records.ProjectControlRecord',
                     'frappe.model.document.Document',
                     'frappe.model.base_document.BaseDocument',
                     'builtins.object'],
 'Cipher Project Duty': ['cipher_aec.cipher_governance.doctype.cipher_project_duty.cipher_project_duty.CipherProjectDuty',
                         'cipher_aec.governance.controllers.DutyDocument',
                         'cipher_aec.governance.controllers.GovernedDocument',
                         'frappe.model.document.Document',
                         'frappe.model.base_document.BaseDocument',
                         'builtins.object'],
 'Cipher Award Adoption': ['cipher_aec.cipher_awards.doctype.cipher_award_adoption.cipher_award_adoption.CipherAwardAdoption',
                           'cipher_aec.awards.records.AwardRecord',
                           'frappe.model.document.Document',
                           'frappe.model.base_document.BaseDocument',
                           'builtins.object'],
 'Cipher Award Line Adoption': ['cipher_aec.cipher_awards.doctype.cipher_award_line_adoption.cipher_award_line_adoption.CipherAwardLineAdoption',
                                'cipher_aec.awards.records.AwardRecord',
                                'frappe.model.document.Document',
                                'frappe.model.base_document.BaseDocument',
                                'builtins.object'],
 'Cipher Award Handoff': ['cipher_aec.cipher_awards.doctype.cipher_award_handoff.cipher_award_handoff.CipherAwardHandoff',
                          'cipher_aec.awards.records.AwardRecord',
                          'frappe.model.document.Document',
                          'frappe.model.base_document.BaseDocument',
                          'builtins.object'],
 'Cipher History Event': ['cipher_aec.cipher_governance.doctype.cipher_history_event.cipher_history_event.CipherHistoryEvent',
                          'cipher_aec.governance.controllers.ScopedImmutableDocument',
                          'cipher_aec.governance.controllers.ImmutableDocument',
                          'cipher_aec.governance.controllers.GovernedDocument',
                          'frappe.model.document.Document',
                          'frappe.model.base_document.BaseDocument',
                          'builtins.object'],
 'Cipher Approval Consumption': ['cipher_aec.cipher_governance.doctype.cipher_approval_consumption.cipher_approval_consumption.CipherApprovalConsumption',
                                 'cipher_aec.governance.controllers.ScopedImmutableDocument',
                                 'cipher_aec.governance.controllers.ImmutableDocument',
                                 'cipher_aec.governance.controllers.GovernedDocument',
                                 'frappe.model.document.Document',
                                 'frappe.model.base_document.BaseDocument',
                                 'builtins.object'],
 'Cipher Command Receipt': ['cipher_aec.cipher_governance.doctype.cipher_command_receipt.cipher_command_receipt.CipherCommandReceipt',
                            'cipher_aec.governance.controllers.ScopedImmutableDocument',
                            'cipher_aec.governance.controllers.ImmutableDocument',
                            'cipher_aec.governance.controllers.GovernedDocument',
                            'frappe.model.document.Document',
                            'frappe.model.base_document.BaseDocument',
                            'builtins.object']}

EXPECTED_SEARCH = ['erpnext.stock.doctype.item.item_search.ItemSearch']

NATIVE_SOURCE_SHA256 = {'erpnext/__init__.py': '3302c7ce0e65088bd7577a3b690c40944457a140be384edb69b0a3d5c287478b',
 'erpnext/controllers/accounts_controller.py': '7cd15abb621544b594fa43e550a95039fa2aa0a6bf395c8464eef01b0bd24d5d',
 'erpnext/controllers/selling_controller.py': 'd7b94b6b089c8bf5a5658b3a9f1e2ee5b111e3832db6cea5e015afff2016f309',
 'erpnext/controllers/status_updater.py': 'a96eb39d3f01a79dc2c26c285ac6aeb2f3f0bb8b2cedebe8a2dee8453dc9e3dc',
 'erpnext/controllers/stock_controller.py': '58de46a8ccfe547a602f87bbfc0e5d144c34ef53cb1cdedb27f6820efc9109ca',
 'erpnext/hooks.py': '28c286e338e7e28cdc8d23cc2168d52251da49c012c21de64d839d484be5c310',
 'erpnext/projects/doctype/project/project.py': 'ababfe01b53da52eaeb999bb77acc7dfa146b714ca1a9a6947cb9fe7e825056d',
 'erpnext/selling/doctype/sales_order/sales_order.py': '062bbcd1bcb9c4c860e972e8a12b605ebc295f5c9a1acbc7af3c5581a9598f9c',
 'erpnext/setup/doctype/transaction_deletion_record/transaction_deletion_record.py': '9d24713bd1f6412a2af1d0988f3932cd43aca6d61ecc27e1639727771603891d',
 'erpnext/stock/doctype/item/item_search.py': 'ef7b31fc79f19f805c3294958b28b6c89952364d5b0a128d5ad85c4012388240',
 'erpnext/support/doctype/service_level_agreement/service_level_agreement.py': '64490465bee6168e46af3a60ba8d4c04ec3fa9e8c6a35dda62ade09ad7fc869a',
 'erpnext/utilities/transaction_base.py': '7e184c78d8392ab15b5ed6b79420b4f56661193384d9bbfa116fbce4101a0ce5',
 'frappe/__init__.py': '933561c566fe4bac7455554f018dd05395f6125111d733ee0a3f3720918c65a4',
 'frappe/automation/doctype/assignment_rule/assignment_rule.py': '369aa6cce1b76e8f0e7ebf6c8abb4d8133709b22316a6cca23e7c33863d5d547',
 'frappe/automation/doctype/automation_flow/automation_flow.json': '91a1151455a1110297e3a854b24957a42fddea086580cb30cb26f9a5675a450d',
 'frappe/automation/doctype/milestone_tracker/milestone_tracker.py': '9393b4bcd85f7dd9c9bcf06cdbb0a3c1e59b2862ba5ef548392d32b4362afa27',
 'frappe/automation_engine/dispatch.py': '76465e6de8ab06378790fa92ddac2f8dc5da237478aaa97b09beb5391feacaca',
 'frappe/automation_engine/registry.py': '54bd851750eab076f585818809a8cb442431031d0dce45c04841bffd793dbb02',
 'frappe/automation_engine/settings.py': '6f9dd36bf5db85f212519d3f8f1965ed8304749137f669d8923715b9beae1e58',
 'frappe/cache_manager.py': 'b1f7515fb4f542aef1d0ec7a450b218517b28bf4f2eca7f6c54dbb2957ee72ac',
 'frappe/config.py': '70047184964bd113ff99e5e91eac0f4233299a65254c950b42a0bf3d8a87aab0',
 'frappe/core/doctype/file/utils.py': '68f8785726e3e71a22ae58f130bbd51defcf661a6384f4b91265fefb9e8339a5',
 'frappe/core/doctype/permission_log/permission_log.py': 'bc039754303f6d730ec7d28f1ad9f761b3d64160eeb282b0be28c68288bd3d00',
 'frappe/core/doctype/server_script/server_script.py': '43303da178c77fc97e7605e76ef90769a69e12ca3486c485085592280f5ebceb',
 'frappe/core/doctype/server_script/server_script_utils.py': 'a428201c350584d35651a42a2171b5586b263c1674ffeed4b04144ae468dc324',
 'frappe/core/doctype/user_type/user_type.py': 'ab276c1ec53c04fe2689f82c7c899988452be08a0f9ddba78a4497e49dc9a3e9',
 'frappe/database/database.py': 'dc9fe0620ab7ceb300bee2b5da5c247d8979727139c785bb591e0a54e3bebf15',
 'frappe/desk/form/assign_to.py': 'e317417e9f7ad0a6c2a60c5238f5c393fe9302b0209c2c9fab11014d624143f1',
 'frappe/desk/notifications.py': '3791cb224e74c218f16c2ce7fec272f993f7d66303a03fb9694f1ab9ef8648cd',
 'frappe/email/doctype/notification/notification.py': 'afabe23c39bd3b82c6c49a7143db9dd51a86916499e0fbcfde141e09f4f8ec9a',
 'frappe/hooks.py': '6c07f57f8adf0e8ee573503fb77dd9af632424079421d7aa12601fe45b1d9696',
 'frappe/integrations/doctype/webhook/__init__.py': '645a562a68282ae57b25dde88022da28b701c4a9c5bbc265854031896a027a7b',
 'frappe/model/__init__.py': '2ae528259240e84738971e2486f5987e9b0b961edca2bc6623aca96900c25103',
 'frappe/model/base_document.py': '61f6242de337314a1ec36dc435d18d853686b9f25deec807d128913bb44cbacd',
 'frappe/model/document.py': '38fc658498a23a42cc8a14ae424591e527c6354d4eada06f12a19644e85b8d00',
 'frappe/model/workflow.py': 'dca11d1ba5fd98b0ab394a91fff97dfd7d31792f53771d097954ce88811dcee4',
 'frappe/permissions.py': 'ae3c1285b87094fef39c27c4a5f73c258da11f955ce45169ca6b4996558f6bd8',
 'frappe/realtime.py': '5bd9cde9fd97cfe0f8050b1be4098bc10907ecb153c79a3bfdcd0e9cf12ce386',
 'frappe/search/full_text_search.py': '0c4411faa728d0109d7f5428cf8c33b82688c94e6258c36f57278dd554640763',
 'frappe/search/sqlite_search.py': '951b2b3416871003d2ea653771416bcb513edf02016dc03a336050ac2167b623',
 'frappe/utils/__init__.py': '5eeffea7bccdc94ce5f7c0ad46678c1152fbe641e30789150a2de097fb7f2277',
 'frappe/utils/global_search.py': 'daf87ba9dd0f9750bbb1f5b188f2c2fa7dad27c10540b482e6606db631d709fd',
 'frappe/utils/safe_exec.py': '5e998ecf01bc66ff37e71b2d3d7e1f9fb895ac389718e257c3e76525fe21c370',
 'frappe/workflow/doctype/workflow_action/workflow_action.py': '23ce2b8e0f51e96509f964d729c2193d081e42ed1fcd00138865d3c32ed8b33d',
 'erpnext/stock/get_item_details.py': '6575f728d188db6236c739b6f5998ba4ec496b5cfe4bdefc3c107c7caca6ec0c',
 'erpnext/stock/doctype/stock_settings/stock_settings.py': '29db5b53fc3afd100bc5eda373848813415939bc7db99124a99c53c7fb383956',
 'erpnext/stock/doctype/stock_settings/stock_settings.json': 'a04abe6c4caf4d23eb20bba7e002b68accd0cb3e04154b5160d6b0f52967032a',
 'frappe/desk/form/document_follow.py': '655186c347706eab2e3358181514daf9f5074a47a7bb4574b91cfd4eae7826d8',
 'erpnext/accounts/doctype/payment_schedule/payment_schedule.py': '715437728a55bcc139f09f46ca1f2f9610b3039a559961c8baa08d2ecf12b1a3',
 'erpnext/accounts/doctype/payment_schedule/payment_schedule.json': '441d6189353c6bd99894382a88058657c61436dd734f596bf1c72a9b3e621906',
 'erpnext/accounts/party.py': 'fce61ad8b869eddd48dc3a03b3067215aec43ae329553fe8940dab0807deb246',
 'erpnext/controllers/taxes_and_totals.py': 'acdf602bdded7d3b39f69858c1c4307c21fa1dde5375bcadf92e6be852dd59e7',
 'erpnext/stock/doctype/packed_item/packed_item.py': 'b475705e19c52a0f54c5c651b9219445cc6007df76001738d76ca7b598b6f270'}

CIPHER_SOURCE_SHA256 = {'cipher_aec/__init__.py': 'aa06f7682da17c65cec391e23e3cbb6e01bb5867fa1f1edff04646779fa7c8f7',
 'cipher_aec/hooks.py': 'e4e5ee93cad36ab39447bb21db6089b3aee0a48e094aa63a639450e176b49dfc',
 'cipher_aec/projects/guards.py': '6f01be2ad8be7c5b349e5e287f3a82911c8a1c344d72c1211a09c9089f09051a',
 'cipher_aec/governance/approvals.py': '18bc4553b06a45974092493f924fb1d694d69708a5cf510b433428526b0135c3',
 'cipher_aec/governance/commands.py': '00a76cb49273487a4bbdeb873fe38d133092feeb41d04bb0652ca6d142218d8e',
 'cipher_aec/awards/effect.py': '934126c93ce2fce06595b7de808f590c01f725116b92972a6de8b8efdf450c62',
 'cipher_aec/awards/runtime.py': 'd703337f602c38282e4081869f2c4d5de4f84217d896d6ad1d45a76ee20b4985',
 'cipher_aec/awards/runtime_profile.py': '74764c0cd64a0b64781ddc6cee2fa0c839271b85cff88fb30c9668238a9bd833',
 'cipher_aec/awards/native.py': 'f4fe2a41565a4fd9ccf28380a5ec7d65b0c58b2184c7a6f07b93a7d9b2284c29',
 'cipher_aec/awards/preallocation.py': '531ecd04e13f5c18ac75bc1403a1df6dab2f5d717cb109b695c74bc265b7b15d',
 'cipher_aec/awards/adoption.py': 'bb1bea285761fe1891da63f942c10569ff9abe16815dfe7d637a6a1af19dcd84',
 'cipher_aec/construction_finance/award_factory.py': 'f815f4a359e420a66de045fce7550f99a56c0f52bdf51a8731bfeed6b3f7bc70',
 'cipher_aec/construction_finance/award_admission.py': '762070cc8644cfe3990176f521b23375d8c742cafc59f97c1618cdd7e7d6500d',
 'cipher_aec/cipher_awards/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/cipher_project_profile/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/cipher_project_profile/cipher_project_profile.py': '5b6ed38511e103418f306c931a63e076d8f9b88ff69959b9e2fcb522a86ebf54',
 'cipher_aec/cipher_awards/doctype/cipher_project_profile/cipher_project_profile.json': '05545b72740cb4b289b3ad1a4aa29ad642335f2acb7cd9c88710413c3a3c83eb',
 'cipher_aec/awards/records.py': '706ba147a6aaf86dde09b704090c9a4d141c5c67365e1256a0e536d5925cbfb9',
 'cipher_aec/cipher_finance/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_finance/doctype/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_finance/doctype/cipher_construction_contract/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_finance/doctype/cipher_construction_contract/cipher_construction_contract.py': '4ad2b5643f08e5ff1338d86401df9a6354556c51db5185c44afa67a49eff3dac',
 'cipher_aec/cipher_finance/doctype/cipher_construction_contract/cipher_construction_contract.json': '429447389b058903540a6c954a05460d59bafebd235aeb99de74571cde9cec7c',
 'cipher_aec/construction_finance/records.py': 'dc4af0410ff4491ab059e31471ba6ef2a070e0222bc73a5a76fda2cede5eee6f',
 'cipher_aec/cipher_project_controls/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_project_controls/doctype/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_version/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_version/cipher_budget_version.py': 'a3a6ac500f766a99827264b2689c99e539afd0c34c9cf19e5f0bec9f4bc1b2a2',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_version/cipher_budget_version.json': '97338b3a44c84c4fd40a14f888efe2add14ee7aa7918d14386f322e1928b5abb',
 'cipher_aec/project_controls/records.py': '4742a9e4c3f88fca2854b80f7dae7e1830d98d175e1f925fd5f127459d275677',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_line/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_line/cipher_budget_line.py': '61e3a59a3e218f5aad7b7143d3b151db612fb1433d7d9526273b33ea3e670b1b',
 'cipher_aec/cipher_project_controls/doctype/cipher_budget_line/cipher_budget_line.json': 'b3d60fdecf7d0285ab1da20fedeb4cdabc3fc30db34c2d3e72df73f3aacd6239',
 'cipher_aec/cipher_project_controls/doctype/cipher_wbs_node/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_project_controls/doctype/cipher_wbs_node/cipher_wbs_node.py': 'cf85123a8f6b942d18d81376bc4d56fb0729038d9618e79a6f75675d0b555d85',
 'cipher_aec/cipher_project_controls/doctype/cipher_wbs_node/cipher_wbs_node.json': 'acc4ae43ad0e3a0a775d8d26d27bda148fc8b2f99e784a89aa5bedfe86d8d04f',
 'cipher_aec/cipher_governance/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/cipher_project_duty/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/cipher_project_duty/cipher_project_duty.py': '30fe48a65929c89e412a26c849904df534240ca02633295ac03d4d3953bffe14',
 'cipher_aec/cipher_governance/doctype/cipher_project_duty/cipher_project_duty.json': '27c4a400c693ff54b58c903e9ae80cf6102e93cdf302c8bcc6790a2ca3a26823',
 'cipher_aec/governance/controllers.py': '5904474140b712626ccb1c6530aa6311114708a3588c627651b67d1168a83c2a',
 'cipher_aec/cipher_awards/doctype/cipher_award_adoption/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/cipher_award_adoption/cipher_award_adoption.py': '0553a81e06610b80378ceb69000323d9e9a3a9976b30fa83362bbff35aa13951',
 'cipher_aec/cipher_awards/doctype/cipher_award_adoption/cipher_award_adoption.json': '3a1890a63b6d6c51b0e93cd3b76e38a91791d147ea9b65a05521c5c6f54d32db',
 'cipher_aec/cipher_awards/doctype/cipher_award_line_adoption/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/cipher_award_line_adoption/cipher_award_line_adoption.py': 'f7f79a8b188893edeb6cc15ab06b186316307c4fed256d2d5a3860c2ce19a403',
 'cipher_aec/cipher_awards/doctype/cipher_award_line_adoption/cipher_award_line_adoption.json': 'ca9f786e8dfb9ca1f64a2aaf5b9ae874bdbafb95de640f704d804129721dd034',
 'cipher_aec/cipher_awards/doctype/cipher_award_handoff/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_awards/doctype/cipher_award_handoff/cipher_award_handoff.py': '91705ddd65b6daed6df49cc062c7a4f60b579317915a2e3d021820c34307ce69',
 'cipher_aec/cipher_awards/doctype/cipher_award_handoff/cipher_award_handoff.json': '8ff4b3aa16cf7406dfd0cb65644d5edc626e01c035e88bc08ac11fadfc5ac931',
 'cipher_aec/cipher_governance/doctype/cipher_history_event/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/cipher_history_event/cipher_history_event.py': '2647f8c7c4e53db2dc29800dccc86d267b64bd97fba52163cbe0653eb720589a',
 'cipher_aec/cipher_governance/doctype/cipher_history_event/cipher_history_event.json': '040b176e0b9814617f9c48b613a0798f6823159d0bcd1ca7ac9ff10a08041719',
 'cipher_aec/cipher_governance/doctype/cipher_approval_consumption/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/cipher_approval_consumption/cipher_approval_consumption.py': '2104d350e30ed60d77031baf12572b4b645ebbefb7dd14fcd8aacc446f7fa8fe',
 'cipher_aec/cipher_governance/doctype/cipher_approval_consumption/cipher_approval_consumption.json': '2f642404549b376ad3f6351ac78b2aaaa7f7b872621c6900581a86135c541bed',
 'cipher_aec/cipher_governance/doctype/cipher_command_receipt/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'cipher_aec/cipher_governance/doctype/cipher_command_receipt/cipher_command_receipt.py': '38aefebda1af450c325e1e3ac167d2694fe9201b59df44e0a13dd0d4bfb1020e',
 'cipher_aec/cipher_governance/doctype/cipher_command_receipt/cipher_command_receipt.json': '01b1e11ecfe5cb35c96b0c03adc5e3d59ee81b3ee35b54300bd2e7eca7bd6582',
 'cipher_aec/awards/repository.py': 'f77664f6b26b116e7dedbc54eb6588133486520bbc3651de2c200d8315f22ae5',
 'cipher_aec/awards/team.py': 'e3f13418e00db76b7617937c94d526838e9811dadda430a10275793f1802231e',
 'cipher_aec/construction_finance/repository.py': '157130705541fefa728bd8cbcd17a50a7414411e5162dabb624c9a54e40756fb',
 'cipher_aec/project_controls/repository.py': '2b8f5b0ec0f4a481d5dad071a02927e44a22e540b82e7c8c907f519ed24f31a6',
 'cipher_aec/governance/history.py': 'b553040c6ff936a0ecc2feb18c350295d0812506b705bd57a25e048061dbb240',
 'cipher_aec/governance/domain_approvals.py': '953c0899cd6a8c040d60571045cffdae726e8187870d6fb07d0211e9e5e2a88e',
 'cipher_aec/awards/governance.py': '4b521cb412bea289f81fa6724b397a6449e9379d53a58fe0280d548a2b4d522f',
 'cipher_aec/documents/provenance.py': '38102145f667cc81b300b595bd00cab7b71bd22f71253d6338482c79fdc89b87'}

def _deny():
    raise DomainError('award_native_catalog_unqualified',
        'The installed native award dispatch catalog requires separate qualification.', 503)


def _source_roots():
    roots = {}
    for app in EXPECTED_APPS:
        spec = find_spec(app)
        if spec is None or not spec.submodule_search_locations or len(spec.submodule_search_locations) != 1:
            _deny()
        roots[app] = Path(next(iter(spec.submodule_search_locations))).resolve()
    return roots


def _require_sources():
    sources = {**NATIVE_SOURCE_SHA256, **CIPHER_SOURCE_SHA256}
    # Check completeness before importing any target hook/controller modules.
    if any(type(value) is not str or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value) for value in sources.values()):
        _deny()
    roots = _source_roots()
    for name, expected in sources.items():
        app, relative = name.split('/', 1)
        path = (roots[app] / relative).resolve()
        if not path.is_relative_to(roots[app]) or sha256(path.read_bytes()).hexdigest() != expected:
            _deny()


def _events(hooks, *, expanded=False):
    if not isinstance(hooks, dict):
        _deny()
    selected = {name: {} for name in (*TARGETS, '*')}
    for key, value in hooks.items():
        keys = (key,) if isinstance(key, str) else key
        if not isinstance(keys, (tuple, list)) or any(type(name) is not str for name in keys):
            _deny()
        if expanded and not isinstance(key, str):
            _deny()
        for target in keys:
            if target not in selected:
                continue
            if not isinstance(value, dict):
                _deny()
            for event, handlers in value.items():
                if type(event) is not str or type(handlers) is not list or any(type(h) is not str for h in handlers):
                    _deny()
                selected[target].setdefault(event, []).extend(handlers)
    return selected


def require_catalog():
    """Require the fixed target catalog; return static policy, never write rights.

    Unrelated DocType hooks/configuration are not banned. The callback profile
    separately checks target configuration and effective cached helpers.
    """
    try:
        _require_sources()
        if frappe.get_installed_apps() != list(EXPECTED_APPS) or frappe.get_installed_apps(_ensure_on_bench=True) != list(EXPECTED_APPS):
            _deny()
        if (_events(frappe.get_hooks('doc_events', {})) != EXPECTED_EVENTS
                or _events(frappe.get_doc_hooks(), expanded=True) != EXPECTED_EVENTS):
            _deny()
        for name in ('override_doctype_class', 'extend_doctype_class'):
            classes = frappe.get_hooks(name, {})
            if not isinstance(classes, dict) or any(classes.get(target) for target in (*TARGETS, '*')):
                _deny()
        if frappe.get_hooks('sqlite_search', []) != EXPECTED_SEARCH:
            _deny()
        from frappe.model.base_document import get_controller
        for target in TARGETS:
            controller = get_controller(target)
            actual = [cls.__module__ + '.' + cls.__qualname__ for cls in controller.__mro__]
            if actual != EXPECTED_MRO[target]:
                _deny()
    except DomainError:
        raise
    except Exception as error:
        raise DomainError('award_native_catalog_unqualified',
            'The installed native award dispatch catalog cannot be qualified.', 503) from error
    return {'catalog': CATALOG}
