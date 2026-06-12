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
