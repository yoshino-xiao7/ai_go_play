# 设计系统阶段 1：项目首页按钮试点（2026-11-19）

本页是带日期的执行记录。规范见 [Token 参考](../docs/design-system/TOKENS.md)「按钮」、[迁移方案](../docs/design-system/MIGRATION.md) 第 4 项和 [样式债务](../docs/design-system/STYLE-DEBT.md) D9。

## 范围

批准范围是迁移方案第 4 项「Button 与 IconButton」的项目首页试点：先建立共用组件，再分批迁移首页自己渲染的入口按钮。

- 不改业务逻辑、其他页面、对话框和卡片菜单的位置，不进入第 5 项。
- 分支 `codex/design-system-phase0`，起点 `db56d65`。只在本地提交，未推送，未合并。

## 组件

`frontend/src/design/Button.tsx` 提供三个组件：

- `Button`：变体为主 / 次 / 幽灵 / 危险，尺寸为 md 40px / sm 32px；
- `ButtonLink`：外观是按钮的链接；
- `IconButton`：必须提供可访问名称。

组件只负责选择类名，其余属性原样传给原生元素，包括可访问名称、`type`、事件、`disabled`、ARIA 属性和 ref。组件不会补默认的 `type`，表单内的提交按钮照常提交。

样式与 Token 见 `design/button.css` 和 [Token 参考](../docs/design-system/TOKENS.md)「按钮」。取值就是现有 `.button` 规则换成 Token 后的结果。状态规则全部沿用已验收的做法：

- 禁用的主按钮：沿用 `states.css` 的共用规则；
- 其他禁用按钮：沿用全局 `button:disabled`；
- 焦点：沿用全局焦点环；
- 悬停：统一带 `:not(:disabled)`。

尺寸按实际渲染保留 40 / 32px。迁移方案建议的 24 / 28 / 32px 会让所有页面按钮变小，需要另行决定。

## 变更

| 提交 | 单元 | 内容 | 可见变化 |
| --- | --- | --- | --- |
| `eb7640a` | B0 | 组件、`button.css`、按钮 Token；`states.css` 的禁用规则加入 `.ui-button--primary` | 无（尚未接入） |
| `39e8232` | B1 | 页头「新手引导」「从亦可导入」「导入项目」「新建画布」，空状态「清除搜索」「新建画布」 | 只有一处：禁用的「导入项目」悬停时不再抬亮底色和描边 |
| `24b428b` | B2 | 项目卡片「…」触发按钮改用 `IconButton` | 冷灰改为语义 Token：图形 `#9299a3` → `--color-text-muted`；悬停 `#e4e9ed` / `#30333a` → `--color-text` / `--color-surface-hover` |
| `c0b3269` | B3 | 三个首页对话框的操作：新建 / 项目设置 / 练习画布的取消与提交；从亦可导入的两个链接与提交 | 无 |

保留不变的内容：

- 可访问名称、`type`（取消按钮保留 `type="button"`，提交按钮仍然没有 `type`）、`disabled` 条件、事件、图标与尺寸；
- `aria-expanded`、卡片菜单的位置与内容；
- `.btn` 悬停上浮动效，属于 D10，继续由调用方传入。

不属于本试点的控件：

| 控件 | 原因 |
| --- | --- |
| 卡片封面、项目名称 | 是整块可点击的卡片区域，不是按钮 |
| 卡片菜单项 | 已在菜单批次中处理 |
| 「重新连接」 | 属于错误横幅，迁移方案中归入 StatusNotice |
| 共用 `Modal` 的关闭按钮、`Confirm` 的取消 / 确认（危险） | 在 `ui.tsx` 中，被所有页面使用，迁移会改变其他页面 |

## 验证方法

- 基线：`e4711fc..db56d65` 只改了文档，`frontend/dist` 的 339 个文件哈希与 `db56d65` 新构建完全一致。因此直接复用上一轮在 `e4711fc` 上的完整采集（146 张），只补拍新增的 15 个首页状态（30 张）。
- 补拍中的 `1920-home-secondary-hover` 截到了封面图尚未加载的画面，属于采集时序问题，与样式无关。这一张在 `db56d65` 上单独重拍；同时采集脚本增加了等待封面加载完成。
- 数据：每次采集都复制一份新的黄金数据，在独立端口上运行。不接触生产素材库，不使用凭据。
- 每批：
  - 执行 `npm run build`（含 `tsc -b`）；
  - `node --test tests/governance.test.cjs` 14/14；
  - 行为检查 `behavior.py` 共 19 项，结果须与 `db56d65` 完全一致（逐字节比较）。覆盖：名称、标签、`type`、Tab 顺序、卡片菜单的点击 / Enter / 空格开关与位置、三个对话框的初始焦点、Escape 与取消、焦点回落、文件选择框、回车提交并跳转、清除搜索；
  - 在 1440×900 与 1920×1080 下采集受影响的状态和相邻对照。按钮类名改变后，指纹键名也会变化，所以比较前先去掉按钮类名，再逐元素比较全部计算样式。
- 交付前：对最终 HEAD 完整采集 88 个状态 × 2 种视口，与基线对比。

本批新增的状态：

| 状态 | 内容 |
| --- | --- |
| `home-secondary-hover`、`home-primary-hover`、`home-secondary-focus` | 页头按钮的悬停与键盘焦点（主按钮焦点沿用 `home-primary-focus`） |
| `fixture-home-import-disabled` | **夹具**：「导入项目」只在导入、复制、保存的短暂过程中禁用，无法稳定采集，所以直接设置 `disabled` 属性后悬停 |
| `home-card-icon-hover`、`home-card-icon-focus` | 卡片「…」的悬停与键盘焦点 |
| `home-search-empty`、`home-search-empty-hover` | 无匹配结果时的「清除搜索」 |
| `home-new-dialog-filled`、`home-new-dialog-cancel-hover`、`home-guide-dialog` | 新建与练习画布对话框（提交禁用见 `home-new-dialog`） |
| `home-share-dialog`、`home-share-dialog-filled` | 从亦可导入：链接为空时提交禁用；填写链接后出现「下载 .manju」 |
| `home-dialog-close-hover` | 共用关闭按钮的悬停（未迁移，作为相邻对照） |
| `fixture-button-variants` | **夹具**：在首页注入旧类和新类成对的按钮板，覆盖四种变体的正常与禁用、sm、链接、图标按钮 |

遮罩与采集条件与前几批相同：遮盖 `.spin`、`progress`、`.storage-stats`、`.path-box`，隐藏 `<video>` 和插入光标。

## 结果

- 夹具板对比：主、次、危险三种变体（正常与禁用）和按钮式链接，与旧类完全一致。按设计有差异的三项：
  - 幽灵变体：文字由冷灰改为 `--color-text-muted`；
  - 图标按钮：由冷灰改为语义 Token；
  - sm 尺寸：字号 12px（旧 compact 为 11px）。
- 每批的非预期差异都是 0，行为检查 19 项都与基线一致。
- 最终 HEAD 对基线：
  - 88 个状态、176 张截图，0 张失败；
  - 147 张像素一致；
  - 去掉按钮类名后，有差异的元素全部是 7 个卡片触发按钮及其图形、禁用「导入项目」的悬停和夹具板；
  - 首页以外的页面全部不变。退出程序对话框打开在首页上，背后的卡片触发按钮计入差异。

## 未覆盖与延期

- 空状态里的「新建画布」主按钮只在资料库为空时出现，黄金数据有 5 个项目，所以没有采集。它与页头主按钮使用同一组件、同一变体。
- 「导入项目」的禁用态只有夹具证据；页头其他按钮没有禁用条件。
- 危险变体和关闭按钮只在共用组件中使用，本试点没有迁移，只用夹具板核对危险变体的取值。
- 窄视口（≤ 700px）没有采集。B1 已让窄视口的 flex 规则同时匹配新类名。
- 统一的图标尺寸（16px、描边 1.5）和 24 / 28 / 32px 尺寸档位没有执行，需要另行决定。
- 其他页面的按钮、旧 `.button.ghost` 与 `.icon-button` 的冷灰、对话框表面的冷灰，都记入 D9。
- 只在 Windows 的无头 Edge 中验证。
