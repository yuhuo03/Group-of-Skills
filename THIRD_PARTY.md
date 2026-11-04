# Third-party components and attribution

- Graph of Skills: the upstream method and evaluation stack; referenced checkout
  commit `203f60a2c689da055ce1ac351eb3cb9912a3bca7`. The local upstream checkout
  includes an MIT license. We do not vendor that whole repository or transfer its
  license to our project. Obtain the upstream checkout with its original license.
- SkillsBench task definitions, Terminal-Bench 2 tasks, ALFWorld/TextWorld data,
  Harbor, and downloaded skill libraries remain external dependencies/assets.
- NumPy, PyYAML, OpenAI client and other optional runtime dependencies retain
  their original licenses. A historical environment inventory is evidence of
  installed versions, not permission to redistribute all assets.

References from the recovered repository documentation:
- https://github.com/davidliuk/graph-of-skills
- https://huggingface.co/datasets/DLPenn/graph-of-skills-data
- https://github.com/benchflow-ai/skillsbench

The archive provenance records which local frozen source files were copied or
adapted. Run the publication checklist before assigning a project license and
uploading. No downloaded task prompts, third-party skill payloads, benchmark
answers, credentials, environment images or model weights are bundled here.
