from copy import deepcopy
from pathlib import Path
import os
import subprocess
import pytest
import yaml
from taps_utils.validate import _check_config_file

RATIONALE = "This one-shot surprise protocol requires every ordered trial and cannot be shortened without changing the experiment."

def fixture(tmp_path):
    (tmp_path/'config').mkdir();(tmp_path/'references').mkdir()
    (tmp_path/'references/audit.md').write_text('Source methods and scientific rationale for complete protocol.',encoding='utf8')
    base={'task':{'total_trials':9,'total_blocks':3,'trial_per_block':3,'conditions':['baseline','critical','control']},'timing':{'cross':.2,'mask':1.5}}
    diag=deepcopy(base);diag['task'].update(diagnostic=True,smoke_preserve_protocol={'rationale':RATIONALE,'reference':'references/audit.md'})
    contract={'name':'config_qa','file':'config/qa.yaml','profile_rules':{'base_file':'config/config.yaml','require_shorter_than_base':True,'allow_equal_when_base_trials_lte':1,'allow_intact_protocol_smoke':True,'require_trials_cover_conditions':True}}
    return base,diag,contract

def check(path,base,diag,contract):
    (path/'config/config.yaml').write_text(yaml.safe_dump(base),encoding='utf8')
    (path/'config/qa.yaml').write_text(yaml.safe_dump(diag),encoding='utf8')
    return _check_config_file(path,contract)

def test_declared_equal_warns_human_review(tmp_path):
    result=check(tmp_path,*fixture(tmp_path))
    assert result.status=='WARN' and any('human review' in m for m in result.messages)

def test_undeclared_shorter_retains_default(tmp_path):
    base,diag,cfg=fixture(tmp_path);diag['task'].pop('smoke_preserve_protocol');diag['task']['total_trials']=6
    assert check(tmp_path,base,diag,cfg).status=='PASS'

def test_undeclared_equal_rejected(tmp_path):
    base,diag,cfg=fixture(tmp_path);diag['task'].pop('smoke_preserve_protocol')
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_contract_must_opt_in(tmp_path):
    base,diag,cfg=fixture(tmp_path);cfg['profile_rules'].pop('allow_intact_protocol_smoke')
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

@pytest.mark.parametrize('mutation',[
    lambda d:d['task'].update(total_trials=12),
    lambda d:d['task'].update(total_trials=6),
    lambda d:d['task'].update(total_blocks=2),
    lambda d:d['task'].update(trial_per_block=2),
    lambda d:d['task'].update(total_trials=9.0),
    lambda d:d['task'].update(diagnostic=False),
    lambda d:d['task'].update(diagnostic=1),
    lambda d:d['task'].update(conditions=['critical','baseline','control']),
    lambda d:d['timing'].update(cross=.1),
    lambda d:d['task'].update(smoke_preserve_protocol=True),
    lambda d:d['task']['smoke_preserve_protocol'].update(rationale=' '),
    lambda d:d['task']['smoke_preserve_protocol'].update(rationale='a'+' '*40+'b'),
    lambda d:d['task']['smoke_preserve_protocol'].pop('rationale'),
    lambda d:d['task']['smoke_preserve_protocol'].update(reference='../references/audit.md'),
    lambda d:d['task']['smoke_preserve_protocol'].update(reference='references/../references/audit.md'),
    lambda d:d['task']['smoke_preserve_protocol'].update(reference='references/missing.md'),
    lambda d:d['task']['smoke_preserve_protocol'].update(reference='references'),
    lambda d:d['task']['smoke_preserve_protocol'].pop('reference'),
])
def test_invalid_declaration_fails_closed(tmp_path,mutation):
    base,diag,cfg=fixture(tmp_path);mutation(diag)
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_absolute_reference_rejected(tmp_path):
    base,diag,cfg=fixture(tmp_path);diag['task']['smoke_preserve_protocol']['reference']=str(tmp_path/'references/audit.md')
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_empty_reference_rejected(tmp_path):
    base,diag,cfg=fixture(tmp_path);(tmp_path/'references/audit.md').write_text(' \n')
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_symlink_escape_rejected(tmp_path):
    base,diag,cfg=fixture(tmp_path);outside=tmp_path/'outside';outside.mkdir();(outside/'audit.md').write_text('An external file',encoding='utf8')
    link=tmp_path/'references/link'
    if os.name=='nt':
        # Directory junctions exercise real Windows resolve behavior without
        # requiring symbolic-link privilege or developer mode.
        subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
    else:link.symlink_to(outside,target_is_directory=True)
    diag['task']['smoke_preserve_protocol']['reference']='references/link/audit.md'
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_base_count_must_also_be_integer(tmp_path):
    base,diag,cfg=fixture(tmp_path);base['task']['total_trials']=9.0
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_other_contract_checks_still_fail(tmp_path):
    base,diag,cfg=fixture(tmp_path);cfg['required_nested_keys']=['qa.required_metadata']
    assert check(tmp_path,base,diag,cfg).status=='FAIL'

def test_non_json_timing_fails_without_crashing(tmp_path):
    from datetime import date
    base,diag,cfg=fixture(tmp_path);diag['timing']['cross']=date(2026,8,31)
    assert check(tmp_path,base,diag,cfg).status=='FAIL'
