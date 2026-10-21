# AI 进球与走位平衡训练包 v3

本目录保留历史 v3 数据；对应代码与权重为提交 `0bae1e205a9af1734b2c8b3d54b12d3cc8208dc9`。下文重现命令应在该历史版本运行；当前代码／权重及新训练命令见 [v4 训练包](../ai_stage3/README.md)。

目标：同时考虑本杆进球、下一杆好打程度与走位代价。允许适度加塞、强一些的高低杆和最多五库换取舒适的下一球。空心入袋仅为小幅软偏好，有利的借袋角仍可推荐。

## 训练与适用范围

- 240个独立初始残局，种子17001–17240；全色和花色两组、1–5颗本组球、黑八及两颗对手球；包含近袋、近库和后方障碍布局。
- 26→12→1价值网络，NumPy/Adam训练1600轮；160/40/40按布局划分训练、验证、测试，只用训练集标准化、只用验证集选权重。具体样本、模拟次数和轮次见 `training-report.json`。
- 标签由有预算的真实模拟续接生成：完成结果结合平均难度、最难一杆和走位代价，未完成给少量进度分。模型预测的是该模拟策略的价值，不是职业或真人进球率。
- 用户案例 `feedback-reference.json` 保持在训练之外；独立对照和逐杆重算练习使用另外的种子，均不反馈到本轮训练。
- 原物理、杆速映射、球台尺寸、练习与反算不变。后斯诺、近库出杆击点和二次击打风险仍检查；目前不支持抬杆、跳球或扎杆。
- 三球以内尽量规划至黑八，更多球先看三杆，实际每杆后重算。允许未清台、无可用方案或因预算中断，不能将其描述为找到全局最优。

## 文件

| 文件 | 内容 |
|---|---|
| `dataset.json` | 全部特征、标签和分支的杆库数、侧击点与袋角记录 |
| `training-report.json` | 训练曲线、保存轮次、留出误差、固定候选排序对照 |
| `independent-audit.json` | 基础/训练版等预算独立规划，逐杆按原规则实际回放 |
| `self-practice.json` | 冻结模型逐杆重算的独立清台练习，含全组七球、两种球组、失败和部分路线 |
| `feedback-reference.json` | 用户提供的台面与旧版路线，用于回归比较 |
| `feedback-comparison.json` | 新旧路线在同一物理与同一评价口径下复盘 |

当前权重：`configs/ai_value_model.json`；独立AI约束：`configs/ai_human_policy.json`。

## 复现

```powershell
python -m tools.train_runout --reuse
python -m tools.audit_runout --layouts 8 --seed 78001
python -m tools.practice_runout --layouts 24 --seed 68001 --seconds 30 --evaluations 1800 --include-feedback --workers 4
python -m tools.evaluate_ai_feedback
```

重新生成训练数据：`python -m tools.train_runout --layouts 240 --workers 4`。需要运行环境允许本地进程间管道；也可用 `--workers 1` 单进程生成相同种子集合。有限时间预算可能受机器性能影响，数据指纹随实际生成结果记录。

数据SHA-256按 `json.dumps(data, sort_keys=True)` 的UTF-8字节计算。

本轮实际88,213次模拟、1,266条样本，保存第140轮权重。独立逐杆练习25局清台19局（含6个整组七球局面），91杆实际执行均通过规则；未完成的6局保留在记录中。独立基础/训练对照8局均清台6局，未证实网络排序本身有额外优势。完整指标与边界见 [部署复核](../../docs/AI进球走位平衡训练与部署.md)。

## 工程评分与来源

本杆难度综合两段距离、进球容错、切角、遮挡净空、手架/近库与长距离目标球。走位杆法代价为 `0.035×杆头速度 + 0.08×|高低击点| + 0.16×|侧击点| + 0.025×库数`。因此三、四、五库都有小额代价，但不会仅因库数被排除；明显更好的下一球能抵消它。

空心软偏好：目标球每次袋角接触加0.12（最多计两次），入袋横向偏移加至多0.06。袋角接触来自实际碰撞事件，未碰袋角不等同于绝对正袋心；横向偏移另记录。全部系数是工程选择，未经职业选手标定。

探索杆头速度上限3.2 m/s，仍低于既有手动5 m/s上限；这是搜索范围，不是白球初速或实测职业极限。后方近库仍限轻柔高杆。侧塞沿用现有二维冲量与碰库模型，未模拟球杆偏移与弧线，因此模型中的侧塞方案需要实桌校准。

- [Dr. Dave：走位原则，留角、三球思考与进入大走位区](https://drdavepoolinfo.com/resource_files/position_play_principles.pdf)
- [Dr. Dave：瞄准容错几何 TP 3.4](https://drdavepoolinfo.com/technical_proofs/TP_3-4.pdf)
- [Dr. Dave：低杆物理与杆速/白球速度区别 TP B.8](https://drdavepoolinfo.com/technical_proofs/new/TP_B-8.pdf)
- [Dr. Dave：侧塞瞄准补偿](https://drdavepoolinfo.com/faq/sidespin/aim/)

参考资料支持一般物理和走位原则，不代表本项目权重或阈值来自职业实测，也不是从职业比赛录像训练。
