# 入口

## 目的

本文档是新 AI 会话进入本项目时使用的轻量入口文档，指定了开发工作流、开发入口规范、默认执行要求。

当用户表达“继续开发这个项目”“继续本项目开发”“从当前进度继续做”等同类意图时，应按以下顺序执行：

## 当前默认工作流

1. 先只阅读：
   - `docs/SESSION_ENTRY.md`
   - `docs/CURRENT_STATUS.md`
   - `docs/PHASE_PROGRESS.md`
   - `docs/DEVELOPMENT_PLAYBOOK.md`
2. 不要预加载全部项目文档。
3. 检查仓库，识别当前 phase，并从下一个未完成实现步骤继续。
4. 只有在当前阶段确实需要时，再读取：
   - `docs/ARCHITECTURE.md`
   - `docs/DECISIONS.md`
   - `docs/PRD.md`
   - `docs/MONTH_PLAN.md`
5. 完成工作后更新：
   - `docs/CURRENT_STATUS.md`
   - `docs/PHASE_PROGRESS.md`
6. 更新前，把旧版本放入 `dev_process_history/`。
7. 归档文件命名要符合对应工作阶段。
8. 更新后的 `CURRENT_STATUS` 和 `PHASE_PROGRESS` 继续放回原位置。

##s/PHASE_PROGRESS.md 和 docs/DEVELOPMENT_PLAYBOOK.md，不要预加载全部项目文档。检查仓库，识别当前 phase，并从下一个未完成实现步骤继续。只有在当前阶段确实需要时，再读取 ARCHITECTURE、DECISIONS、PRD 或 MONTH_PLAN。完成工作后更新 CURRENT_STATUS 和 PHASE_PROGRESS。更新前的CURRENT_STATUS 和 PHASE_PROGRESS放到文件夹dev_process_history里面，并且CURRENT_STATUS 和 PHASE_PROGRESS的命名需要符合其工作阶段。更新后的CURRENT_STATUS 和 PHASE_PROGRESS代替之前的CURRENT_STATUS 和 PHASE_PROGRESS放在原地。

#### 开发规范入口

1. 涉及开发规范、代码风格、注释策略、描述语言选择时，先阅读 `docs/代码可读性规范.md`。
2. 开发过程中按 `docs/代码可读性规范.md` 执行。

## 默认执行要求

1. 开发时同步检查是否缺少白话中文注释。
2. 凡是描述类内容，默认使用中文。
3. 只有在标识符、协议字段、命令名、标准库名等必须保留英文的场景，才保留英文。
4. 以第一性原理思考，先从原始需求和问题本质出发，不从惯例、模板或“大家一般这样做”出发。
5. 不要假设用户已经清楚自己需要什么；如果动机或目标不清晰，应先停下来讨论，再继续执行。
6. 如果目标清晰，但当前路径不是更短、更直接或更本质的办法，应直接指出，并建议更好的路径。
7. 遇到问题优先追根因，不做只掩盖表象的补丁；每个关键决策都应能回答“为什么这样做”。
8. 输出只保留会改变判断、路径或决策的信息，其余信息默认删掉。
9. 测试默认使用虚拟环境 `D:\jt\ANACONDA\envs_dirs\learn-claude-code`，显式调用 `D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe`；不要默认使用系统 PATH 或 Codex 内置 Python。
