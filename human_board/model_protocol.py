"""Fail-closed parsing shared by all model-facing entry points. No network I/O."""
import json


class ResponseError(ValueError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def completed_output(payload):
    if not isinstance(payload, dict): raise ResponseError('invalid_response','Response must be an object')
    status = payload.get('status')
    if status != 'completed':
        kind = status if status in ('failed','incomplete','cancelled','queued','in_progress') else 'invalid_response'
        raise ResponseError(kind,'Response not completed: '+str(status))
    if payload.get('error') or payload.get('incomplete_details'):
        raise ResponseError('provider_error','Provider error or incomplete details present')
    output = payload.get('output')
    if not isinstance(output,list) or not output:
        raise ResponseError('empty_output','No completed decision in response')
    for item in output:
        if not isinstance(item,dict): raise ResponseError('invalid_response','Invalid output item')
        if item.get('type') not in ('message','function_call','reasoning'):
            raise ResponseError('unexpected_output','Unexpected output item type')
        if item.get('type') in ('message','function_call') and item.get('status') != 'completed':
            raise ResponseError('incomplete','Output item not completed')
        if item.get('type') == 'message':
            content = item.get('content')
            if not isinstance(content,list) or not content: raise ResponseError('invalid_response','Empty message')
            for part in content:
                if not isinstance(part,dict): raise ResponseError('invalid_response','Invalid message part')
                if part.get('type') == 'refusal': raise ResponseError('refusal','Model refused')
                if part.get('type') != 'output_text' or not isinstance(part.get('text'),str):
                    raise ResponseError('invalid_response','Unexpected message content')
    return output


def parse_text_response(payload):
    output = completed_output(payload)
    if any(x['type']=='function_call' for x in output): raise ResponseError('unexpected_tool','Unexpected function')
    parts = [p['text'] for x in output if x['type']=='message' for p in x['content']]
    if not parts: raise ResponseError('empty_output','Missing decision text')
    result = json.loads(''.join(parts))
    if not isinstance(result,dict) or result.get('decision') not in ('no_human','request_human'):
        raise ResponseError('invalid_decision','Invalid decision JSON')
    if not isinstance(result.get('reason'),str) or not result['reason'].strip():
        raise ResponseError('invalid_decision','Decision reason required')
    return result


def parse_tool_response(payload, tool_name):
    output = completed_output(payload)
    calls = [x for x in output if x['type']=='function_call']
    if len(calls)>1: raise ResponseError('multiple_calls','Multiple fieldwork calls disallowed')
    if calls:
        if calls[0].get('name') != tool_name: raise ResponseError('unexpected_tool','Unknown function')
        args = calls[0].get('arguments')
        if not isinstance(args,str): raise ResponseError('invalid_arguments','Arguments must be a JSON string')
        value = json.loads(args)
        if not isinstance(value,dict): raise ResponseError('invalid_arguments','Arguments must be an object')
        return {'choice':'request_human','proposal':value,'model_response_id':payload.get('id')}
    result = parse_text_response(payload)
    if result['decision'] != 'no_human':
        raise ResponseError('missing_tool','Text claims fieldwork but tool was not called')
    return {'choice':'no_human','proposal':None,'reason':result['reason'],'model_response_id':payload.get('id')}


TOOL_INSTRUCTIONS = ('\n필요할 때만 request_human_fieldwork 도구를 호출하라. 도구 호출은 초안이며 실제 게시가 아니다. '
                     '불필요하면 도구를 호출하지 말고 JSON {"decision":"no_human","reason":"구체적인 사유"}를 출력하라.')
