"""Actual D ALFWorld request protocol, with explicit dependency injection.

Pass the official GoS SkillModule class. No task-specific legacy ALF selector is
used. Retrieval sees the visible goal/current blocker, never an episode answer.
"""
from .common import write
from .retrieval import DContext

def d_skill_class(SkillModule):
 class DSkills(SkillModule):
  def __init__(self,directory,skills_root,pool,source_root="/opt/graphskills/skills"):
   super().__init__(skills_dir=str(skills_root),model='gpt-5.4',mode='none',enable_alfworld_gating=False)
   self.mode='gos';self.directory=directory;self.n=0
   self.context=DContext(pool,source_root)
  def retrieve_relevant_skills(self,task,top_k=4):
   self.n+=1;self.bundle=self.context.query(task)
   write(self.directory/'retrievals'/f'{self.n:04d}.json',self.bundle,True)
   self.last_retrieved_skill_names=[s['name'] for s in self.bundle['presented_skills']];self.last_retrieval_query=task;self.last_retrieval_status='SKILL_HIT' if self.last_retrieved_skill_names else 'NO_SKILL_HIT';self.last_retrieval_summary=self.bundle['rendered_context']
   return [s['rendered'] for s in self.bundle['presented_skills']]
  def get_retrieval_guidance(self):return self.bundle['rendered_context']
  def get_agent_skill_request_message(self):
   return ('GoSkills D provides an execution contract from the current visible query. Follow applicable skills conditionally. '
           'For a focused new retrieval use `Thought: ...` then `SkillRequest: GOS_RETRIEVE <current visible goal or blocker>`. '
           'To read a named skill use `SkillRequest: READ_SKILL <exact skill name>`. Each request consumes one interaction step; do not also emit Action.')
  def handle_agent_skill_request(self,task,response,current_step):
   kind,payload=self._parse_skill_request(response)
   if kind=='gos_retrieve' and payload:
    self.retrieve_relevant_skills(payload);self._record_runtime_skill_event(current_step,'agent_request:goskills_d',payload,self.last_retrieved_skill_names);return self.get_retrieval_guidance()
   return super().handle_agent_skill_request(task,response,current_step)
  def maybe_get_runtime_skill_hint(self,task,messages,observation,current_step):
   # New benchmark interface choice: explicit requests only, no cross-episode failure traces.
   return ''
 return DSkills


def official_skill_class(SkillModule):
 """Keep upstream all_full/vector/graph ALFWorld behavior, including query shaping."""
 from .method_backend import OfficialRetriever
 class OfficialSkills(SkillModule):
  def __init__(self,mode,directory,skills_root,workspace=None,upstream=None):
   # Construct metadata without triggering the upstream default LLM/embedding services.
   super().__init__(skills_dir=str(skills_root),model='gpt-5.4',mode='none',enable_alfworld_gating=False)
   self.mode=mode
   if mode in {'gos','vector'}:
    self.gos_workspace=str(directory/'index')
    self.rag=OfficialRetriever(directory,workspace,upstream)
 return OfficialSkills


def make(method,SkillModule,directory,*,skills_root=None,pool=None,workspace=None,upstream=None):
 from pathlib import Path
 from .method_backend import validate_resources
 validate_resources(method,skills_root=skills_root,pool=pool,workspace=workspace,upstream=upstream,check_files=True)
 if method=='noskills':return None
 if method=='goskills-d':return d_skill_class(SkillModule)(Path(directory),skills_root,pool)
 return official_skill_class(SkillModule)({'vanilla':'all_full','vector':'vector','native-gos':'gos'}[method],Path(directory),skills_root,workspace,upstream)
