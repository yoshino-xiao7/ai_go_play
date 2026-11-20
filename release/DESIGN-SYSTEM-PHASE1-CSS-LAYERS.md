# 设计系统阶段 1：CSS 分层（2026-11-20）

本页是带日期的执行记录。级联结构见 [级联审计](../docs/design-system/CASCADE-AUDIT.md)，问题见 [样式债务](../docs/design-system/STYLE-DEBT.md) D8。

## 范围与前提

批准范围是迁移方案第 9 项（D8）：只迁移可以证明安全的部分，不做大范围重排，不清除 `!important`，也不建立没有内容的空层。

迁移方案要求先基本清理 `!important`，这一前提尚未满足：21 个文件中仍有 211 处 `!important`，其中 102 处与同一属性上的其他 `!important` 争夺。因此应用样式全部保持未分层。

分支 `codex/design-system-phase0`，起点 `72a3f4c`。只在本地提交，未推送，未合并。

## 依据：层叠规则实测（Edge 157，8/8）

- 未分层的普通声明胜过分层的普通声明，与特异性和源顺序都无关。
- `!important` 优先级反转：分层的胜过未分层的；层之间，先声明的层胜出。
- 同一层内先比特异性，特异性相同再比源顺序。
- 后来插入（懒加载）的样式表加入已声明的层后，仍低于所有未分层规则。

由此推出迁移条件：

- 含 `!important` 的文件不能分层，否则会反转它们与其他 `!important` 的胜负。
- 普通规则分层后会降到所有未分层规则之下，只有在它们目前从未胜过未分层规则时才安全。

## 变更

| 提交 | 单元 | 内容 | 安全依据 |
| --- | --- | --- | --- |
| `acd1570` | V1 | React Flow 基础样式改由 `styles.css` 以 `layer(vendor)` 导入，删除 `Canvas.tsx` 中的重复导入 | vendor 样式没有 `!important`。上线前实验：把两份已加载的 vendor 规则（每份 105 条，其中 32 条被压缩器改写过）全部移入 `@layer vendor`，9 个状态 × 2 种视口中每个元素的计算样式 0 差异 |
| `e3aa5eb` | L2 | `tokens.css` 开头声明层顺序 `@layer tokens, vendor;`，全部 `:root` 自定义属性放入 `@layer tokens` | 只有自定义属性，没有 `!important`；130 个名字在其他地方都没有定义，也没有脚本内联设置；实测 130 个值前后完全一致 |

V1 同时修正了一个真实的懒加载顺序问题。之前构建结果是入口 CSS 和 Canvas 块 CSS 各带一份 React Flow 样式；打开画布时，第二份未分层的规则会插到全局主题之后。现在只有一份，位于最低层。

## 保留未分层的部分

| 范围 | 原因 |
| --- | --- |
| 含 `!important` 的 21 个文件 | 分层会反转 `!important` 的优先级 |
| `studio-theme.css`、`management.css` | 依靠前缀特异性和 `!important` 覆盖之后懒加载的组件样式 |
| `design/states.css` | 禁用态必须胜过组件提交按钮的规则 |
| `design/button.css`、组件样式 | 它们需要胜过全局基础规则（例如 `button { color: inherit }`） |
| `styles.css` 其余部分 | 含 `!important`；而且是组件样式要覆盖的基础规则 |

尚未解决的懒加载覆盖：

- 组件块插在主题之后，主题仍靠特异性和 `!important` 覆盖它们。
- `video.css` 等文件被多个块导入，插入时机取决于先打开的界面。
- 后置覆盖块中仍有 122 处 `!important`（`canvas.css` 99 处、`canvas-project-menu.css` 12 处、`timeline.css` 11 处）。

逐条清单见交付目录中的《!important 与覆盖关系审计》。

## 验证

- 每批：
  - `npm run build`（含 `tsc -b`）；
  - `node --test tests/governance.test.cjs` 14/14；
  - 两种视口下的定向回归，逐元素比较计算样式和像素：V1 32/32 一致，L2 28/28 一致。
  - 覆盖的状态：
    - 懒加载顺序（先打开首页，再通过真实点击进入画布）；
    - 画布的选中、连线、框选、手柄与节点悬停、分组、面板、缩放、右键菜单、工具栏悬停；
    - 首页的悬停、焦点和禁用夹具；
    - 资产、设置、安装向导；
    - 视频参数、选择框、生成参数、时间线、项目菜单。
- 构建产物：
  - 入口 CSS 以 `@layer tokens,vendor;` 开头，包含 1 个 tokens 块和 1 个 vendor 块；
  - Canvas 块中不再有 React Flow 规则；
  - 在页面中实测，只有 1 条层顺序声明和 1 个 vendor 块。
- 最终 HEAD 完整采集（102 个状态 × 2 种视口）：
  - 204 张，0 张失败，0 处元素变化，203 张像素一致；
  - 唯一的例外 `1440-reference-picker` 来自复用的基线：第 8 项最终采集的那一张缩略图尚未加载完成。本次截图与第 8 项在同一状态的复拍完全一致（0 像素差异）。

## 未覆盖

- React Flow 的 MiniMap、Controls、Attribution、背景线条 / 十字图案在本应用中不渲染，只有静态推理：这些规则没有 `!important`，应用中也没有与之竞争的规则。
- 窄视口没有采集。
- 其他懒加载块之间的全部打开顺序组合没有逐一验证。
- 只在 Windows 的无头 Edge 中验证。
