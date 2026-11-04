"""SkillsBench direct API agent import for an explicitly prepared Harbor task pack.

The base is the shared frozen direct-API agent. SkillsBench D retrieval is injected
by the task-pack skill-query tool/bootstrap, not the TB2 system prompt. See README.
"""
from goskills_eval.harbor_base import DirectAPIBashAgent
