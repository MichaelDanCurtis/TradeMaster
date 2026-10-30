"""Export agent tool receipts without private reasoning or system instructions.

This is an observable tool-call audit, not a proof of no learned hindsight.
"""
from pathlib import Path
import argparse,json,hashlib,re

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--sessions',type=Path,required=True);a=ap.parse_args();records=[]
 for path in sorted(a.sessions.glob('*.jsonl')):
  with path.open() as f:
   first=json.loads(next(f));meta=first.get('payload',{});agent=meta.get('agent_path','')
   if not agent.startswith('/root/astra_'):continue
   cid=agent.removeprefix('/root/astra_').replace('_','-');calls=[];contexts=[];prompts=[]
   for line in f:
    try:d=json.loads(line)
    except json.JSONDecodeError:continue
    p=d.get('payload',{})
    if d.get('type')=='turn_context':contexts.append({k:p.get(k) for k in ['model','effort']})
    elif d.get('type')=='response_item':
     if p.get('type') in ['function_call','custom_tool_call']:
      calls.append({'timestamp':d.get('timestamp'),'type':p['type'],'name':p.get('name'),'input':p.get('input',p.get('arguments'))})
     elif p.get('type')=='message' and p.get('role')=='user':
      text='\n'.join(c.get('text','') for c in p.get('content',[]) if isinstance(c,dict));prompts.append(text)
  text='\n'.join(str(c['input']) for c in calls)
  packet_refs=set(re.findall(r'(?:packets[/\\]+|packets[^\n]{0,10})(?:[\'\"])?((?:blind|named)-\d{3})\.json',text))
  literal_refs=set(re.findall(r'(?:blind|named)-\d{3}\.json',text))
  external_tools=[c['name'] for c in calls if c['name'] not in ['exec','exec_command','write_stdin','wait','apply_patch','functions.exec']]
  flags=[]
  if any(c.get('model')!='gpt-6-astra' for c in contexts):flags.append('unexpected model')
  if external_tools:flags.append('inspect additional tools: '+repr(external_tools))
  if literal_refs-{cid+'.json'}:flags.append('other case literal references: '+repr(literal_refs-{cid+'.json'}))
  # These patterns are only review flags: prose disclaimers can also match.
  suspect_patterns=['tools.web__','tools.mcp__','collaboration.','urllib','import requests','http://','https://','/memories/','results.json','private/cases','prediction-wide','os.walk','rglob(','glob(']
  for pattern in suspect_patterns:
   if pattern in text:flags.append('review pattern: '+pattern)
  records.append({'case_id':cid,'agent_task':agent,'agent_id':meta.get('id'),'model_contexts':contexts,'initial_prompts':prompts,'tool_calls':calls,'observed_case_file_references':sorted(literal_refs),'flags':flags,'source_transcript_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 result={'scope':'Observable calls and supplied prompts only; not an OS sandbox, not proof about pretrained knowledge','agent_count':len(records),'tool_call_count':sum(len(x['tool_calls']) for x in records),'flagged_cases':[{'case_id':x['case_id'],'flags':x['flags']} for x in records if x['flags']],'agents':records}
 (a.root/'access-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='agents'}))
if __name__=='__main__':main()
