"""V1.1 authenticated synthetic replay, preserving historical entry point. No model or payment."""
import json
from pathlib import Path
from agent_tool_v08 import check_proposal
from agent_trial import SCENARIOS
from mission_bridge import run_scenario


def simulate_one(scenario_id='physical_gap'):
    scenario = next((s for s in SCENARIOS if s['id']==scenario_id),None)
    if scenario is None: raise ValueError('Unknown fixture')
    draft = dict(title='공공 안내문 가독성 확인',location='사전 허가된 공개 보행 공간',
                 scope='공개 보행 구간의 안내문 관찰',evidence_request='텍스트 관찰 원문',
                 max_budget_krw=5000,reason='온라인 문서로 실제 설치 상황을 검증할 수 없음')
    error = check_proposal(scenario,draft)
    if error: return dict(fixture=scenario_id,outcome='rejected_by_guard',reason=error,synthetic=True)
    flow = run_scenario(scenario)
    if flow['mission_status'] != 'resumed_with_unverified_field_observation': raise RuntimeError(flow)
    return dict(fixture=scenario_id,outcome='accepted_simulation',task_id=flow['task_id'],
                events=[action for action in flow['audit_events'] if action in ('created','claimed','submitted') or action.startswith('review_')],
                mission_feedback=dict(mission=scenario['mission'],observation=flow['feedback_to_mission']['evidence'],
                    ground_truth_confirmed=False,next_action='현장 데이터로 간주하지 말고 독립 검증 요청'),
                review_method='MANUAL_SYNTHETIC_REVIEW',payment='NOT_PAID',synthetic=True,model_tool_selection='NOT_TESTED')


def run():
    return dict(version='1.1',type='synthetic local replay',
                runs=[simulate_one(c) for c in ('physical_gap','online_sufficient','no_money','high_risk')],
                no_real_workers=True,no_model_calls=True,no_payments=True)


if __name__=='__main__':
    result=run()
    out=Path(__file__).with_name('e2e_v11_results.json')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(out),'outcomes':[x['outcome'] for x in result['runs']]},ensure_ascii=False))
