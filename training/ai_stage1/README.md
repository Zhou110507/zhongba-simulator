# AI 第一阶段训练包

目标是给出普通人类杆法范围内的清台思路，优先考虑进球、自然衔接、下一杆架杆、适中击球距离与角度，并继续考虑再下一杆。模型不是职业选手成功率预测器。

## 训练方式

- 使用本项目 CBSA 规则台型的原物理内核生成 1–3 颗本方球＋黑八＋两颗对方球的残局；部分布局刻意包含近库和白球后方障碍。
- 每个布局尝试多个首杆，继续用有预算的普通杆法策略完成后续击球。
- 标签由实际模拟的续接/清台结果与后续难度计算：完成路线按难度折减，未完成路线只给少量进度分。低分不证明局面无法清台。
- 普通杆法先检查后方球杆空间、近库击点、过近二次击打风险；限制切角、杆速、距离和库数，排除借碰其他球续接的候选。
- 用 NumPy 实现 20 输入、12 隐层、1 输出的 tanh/sigmoid 网络，Adam 训练 1600 轮；只根据验证集选择保存轮次。
- 按初始布局划分 80 个训练布局、20 个验证布局、20 个测试布局，同一布局中的各杆不会跨集合。
- 固定数据生成种子 17001–17120、网络种子 20261021。独立规划对照另用 28001 开始的布局。

## 文件

- `dataset.json`：训练与留出评估的全部特征、标签、种子和候选结果。没有职业比赛录像数据。
- `training-report.json`：训练曲线、所选轮次、留出误差及候选排序对照。
- `independent-audit.json`：另外一组布局上等预算规划与逐杆完整回放的验证结果。
- 模型参数位于 `configs/ai_value_model.json`，普通杆法限制位于 `configs/ai_human_policy.json`。

## 复现

在项目根目录运行：

```powershell
python -m tools.train_runout --reuse
python -m tools.audit_runout --layouts 12
```

重新生成布局与训练数据：

```powershell
python -m tools.train_runout --layouts 120
```

`dataset_sha256` 为数据对象经 `json.dumps(data, sort_keys=True)` 编码后的 SHA-256，用于核对数据内容。生成的完整场景也可通过布局种子还原。

## 适用范围

这是小规模模拟训练。误差指标衡量对当前模拟策略价值标签的拟合；候选对照中的清台次数是固定候选集上的回放结果；均不代表真人实桌成功率。普通杆法限制中的数值为保守工程设置，未经特定选手标定。模型不能保证找到全局最优路线；多球对局目前只有两杆前瞻，复杂解堆、防守和抬杆仍待后续阶段。

参考：

- [Dr. Dave：八球关键球、连接球和路线实例](https://drdavepoolinfo.com/bd_articles/2014/feb14.pdf)
- [Dr. Dave：抬杆与低杆](https://drdavepoolinfo.com/faq/draw/cue-elevation/)
- [Dr. Dave：二次击打风险](https://drdavepoolinfo.com/faq/foul/double-hit/)
- [Computational Pool：候选生成、带误差评估和前瞻](https://ai.stanford.edu/~shoham/www%20papers/CompPool%20AIMag%202010.pdf)
