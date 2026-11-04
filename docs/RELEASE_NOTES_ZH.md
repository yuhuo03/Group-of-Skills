# GPT-5.4 五方法评测版本

本地代码候选版本 0.2.0rc2 沿用原仓库结构，使用本轮 candidate-D 核心。
原代码、冻结文件和实验成绩均保留；未上传 GitHub，也未调用模型或重跑实验。

## 本次补齐

- SkillsBench、ALFWorld、TB2 × No Skills / Vanilla / Vector / Graph of Skills / GoSkills D，共15组入口。
- SkillsBench 从原始任务自动生成方法包；ALFWorld 提供134项任务映射及哈希。
- 真实上游向量、图检索与D检索分别接入，保留各benchmark原提示及方法差异。
- README → DATA → doctor → 单任务或批量计划/执行 → CSV/JSON汇总的完整使用路径。
- 默认只计划；显式 --execute 才开始实验。独立输出、失败停派、无自动分数重试。
- 完整记录reward、input/output tokens、agent runtime、轨迹及验证回执。
- 汇总检查回执身份/哈希，整目录移动后仍能汇总；缺失结果不算零分。
- 核心10模块及1545项历史数据未改；源码来源和包装改动单独记录。

## 验证范围

离线单元/集成测试使用假的模型与环境，不产生真实实验分数。
实际Harbor0.20配置schema已核对；精确验证项、环境和测试数量见
[RELEASE_VALIDATION](../provenance/RELEASE_VALIDATION.json)。
新的付费API/Docker/模拟器端到端实验没有执行。

完整评测建议Linux/Python3.12。任务镜像、技能库、索引及外部依赖按DATA.md准备。
新建索引或下载当前SkillsBench任务属于新输入；不声称逐字节重现历史环境。
原环境修复源码继续保留在独立trace artifacts中。

TB2的60.7%仍明确为44原成功+45原零分复测的条件替换结果，保留原49.4%对照。
项目LICENSE、最终GitHub地址和论文DOI仍待作者确定；本包未虚构授权或发布信息。
