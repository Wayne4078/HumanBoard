"""Authenticated synthetic state rehearsal, NOT AI judgement or real field verification."""
import json
from agent_trial import baseline, SCENARIOS, validate
from simulation import Sandbox


def run_scenario(scenario, evidence=None, approve=True, reviewer_decision='accepted'):
    proposal = baseline(scenario)
    outcome = {'scenario':scenario['id'],'source':'explicit-rule-baseline; not autonomous AI',
               'decision':proposal['decision'],'events':[],'mission_status':'pending'}
    if validate(proposal,scenario):
        outcome['mission_status']='blocked_invalid_proposal'; return outcome
    if proposal['decision']=='no_human':
        outcome['mission_status']='completed_with_available_data' if '최근 표본 조사 완료' in scenario['facts'] else 'paused_for_authorization_or_expert'
        return outcome
    if not approve:
        outcome['mission_status']='waiting_for_human_approval'; return outcome
    with Sandbox() as box:
        code, result = box.mission(budget=scenario['budget_krw'])
        if code != 201: raise RuntimeError(result)
        task = proposal['task']
        draft = box.draft(title=task['title'],scope=task['scope'],evidence_request=task['evidence_request'],budget=task['max_budget_krw'])
        code,result = box.order(draft)
        if code != 201:
            outcome.update(mission_status='posting_failed',error=result); return outcome
        tid = result['task_id']; outcome.update(task_id=tid); outcome['events'].append('posted')
        calls = [('claim_task',dict(task_id=tid),'worker'),
                 ('submit_evidence',dict(task_id=tid,evidence=box.evidence(evidence or 'SYNTHETIC 관찰: 출입구 하나가 일시 폐쇄됨; 실제 현장 증빙 아님.')),'worker')]
        for action,p,who in calls:
            code,result = box.call(action,p,who)
            if code != 200:
                outcome.update(mission_status='flow_failed',error=result); return outcome
            outcome['events'].append(action)
        code,result = box.review(tid,reviewer_decision)
        if code != 200:
            outcome.update(mission_status='flow_failed',error=result); return outcome
        outcome['events'].append('review_task')
        _,stored = box.call('get_task_status',dict(task_id=tid))
        _,ev = box.call('get_evidence',dict(task_id=tid))
        outcome['feedback_to_mission'] = dict(task_id=tid,evidence=ev['evidence']['observation'],
            evidence_quality='UNVERIFIED_SYNTHETIC',review_status=stored['status'],
            review_method='MANUAL_SYNTHETIC_REVIEW',ground_truth_confirmed=False,human_payment='NOT_PAID_SIMULATION')
        _,audit = box.call('audit',dict(task_id=tid),'admin')
        outcome['audit_events'] = [event['action'] for event in audit['events']]
        outcome['mission_status']='resumed_with_unverified_field_observation' if reviewer_decision=='accepted' else 'waiting_for_reliable_evidence'
        return outcome


def run_suite(): return [run_scenario(s) for s in SCENARIOS]


if __name__=='__main__': print(json.dumps(run_suite(),ensure_ascii=False,indent=2))
