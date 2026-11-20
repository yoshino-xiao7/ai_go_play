# Token 参考

定义文件：`frontend/src/design/tokens.css`。「已接入」表示当前界面通过语义 Token 或历史别名实际使用它；「建议」表示已定义、尚未被任何规则引用，首次接入需要作为视觉变更评审。规则与流程见 [Design System](README.md)。

## 颜色

| Token | 值 | 用途 | 状态 |
| --- | --- | --- | --- |
| `--color-bg-canvas` | `#161415` | 画布底色 | 已接入（`--canvas-bg`） |
| `--color-bg-app` | `#181617` | 应用底色 | 已接入（`--bg`） |
| `--color-surface-chrome` | `#1e1b1c` | 导航栏、顶栏 | 已接入（`--rail`） |
| `--color-surface-sunken` | `#151314` | 管理页输入框 | 已接入（`--admin-input`） |
| `--color-surface-panel` | `#242022` | 面板 | 已接入（`--panel`） |
| `--color-surface-raised` | `#2d282a` | 浮层、弹出菜单 | 已接入（`--panel-raised`） |
| `--color-surface-hover` | `#3e3037` | 抬升表面上的悬停 | 已接入（`--popup-hover`） |
| `--color-canvas-grid` | `#41383d` | 画布点阵 | 已接入（`--canvas-grid`） |
| `--color-border` | `#3b3337` | 细分隔线 | 已接入（`--border`） |
| `--color-border-strong` | `#55464e` | 强边框 | 已接入（`--border-light`） |
| `--color-text` | `#f4eef1` | 主文字 | 已接入（`--text`） |
| `--color-text-muted` | `#b6a9af` | 次要文字 | 已接入（`--muted`） |
| `--color-accent` | `#f3abc2` | 选中、主操作、已采用 | 已接入（`--accent`） |
| `--color-accent-hover` | `#ffd0df` | 主操作悬停 | 已接入 |
| `--color-accent-line` | `#a96e86` | 强调描边 | 已接入 |
| `--color-accent-soft` | `#f3abc21a` | 选中底色 | 已接入 |
| `--color-on-accent` | `#2d1720` | 强调色上的文字 | 已接入（`--accent-ink`） |
| `--color-success` | `#adc7bf` | 成功 | 已接入（`--status-ok`） |
| `--color-danger` | `#f0907a` | 危险操作与失败。色相与品牌色相差 30.4°；作为文字在所有表面上对比度不低于 5.3:1 | 已接入（阶段 1） |
| `--color-danger-soft` | `#f0907a24` | 危险提示底色、危险按钮悬停（14%） | 已接入 |
| `--color-danger-line` | `#f0907a59` | 危险控件描边（35%） | 已接入 |
| `--color-danger-solid` | `#be5337` | 填充式危险按钮（如确认删除）。白字对比度 4.7:1，与弹窗表面对比 3.5:1 | 已接入 |
| `--color-on-danger-solid` | `#ffffff` | 填充式危险按钮上的文字 | 已接入 |
| `--color-warning` | `#d7ad73` | 警告与阻塞提示。作为文字不低于 6.0:1（在自身底色上同样成立） | 已接入（阶段 1） |
| `--color-warning-soft` / `--color-warning-line` | 12% / 35% | 警告底色 / 描边 | 已接入 |
| `--color-info` | `#9ebfe8` | 说明与模式提示，不用于选中或主操作。作为文字不低于 6.6:1 | 已接入（阶段 1） |
| `--color-info-soft` / `--color-info-line` | 12% / 35% | 信息底色 / 描边 | 已接入 |
| `--color-focus` | 同 accent | 所有键盘焦点环 | 已接入（阶段 1） |
| `--color-disabled-surface` | 同 surface-raised | 禁用的主操作背景 | 已接入（阶段 1） |
| `--color-disabled-border` | 同 border | 禁用的主操作描边 | 已接入 |
| `--color-disabled-text` | 同 text-muted | 禁用的主操作文字，在禁用背景上对比度 6.4:1 | 已接入 |

危险色最初建议为 `#e5735a`。实测它在悬停表面上的文字对比度只有 4.1:1，低于小字号所需的 4.5:1，所以改为 `#f0907a`。

基础色阶 `--ink-*`、`--rose-*` 只在 `tokens.css` 内部引用。

## 文字

| Token | 值 | 用途 | 状态 |
| --- | --- | --- | --- |
| `--font-ui` | Segoe UI, PingFang SC, Microsoft YaHei, system-ui | 界面字体 | 已接入（根元素） |
| `--font-mono` | Cascadia Code, Consolas, Microsoft YaHei, monospace | 路径、代码 | 建议（当前有 4 套等宽字体写法） |
| `--text-xs` | 11px | 数字和英文元数据；不用于中文正文 | 已接入（时间线：尺标时间、播放时间、片段与素材时长） |
| `--text-sm` | 12px | 标签、说明 | 已接入（时间线中文文字、画布状态栏） |
| `--text-md` | 13px | 界面正文 | 已接入（时间线选中片段名） |
| `--text-lg` | 14px | 强调正文、设置页正文 | 已接入（时间线标题） |
| `--text-xl` | 16px | 区块标题 | 建议 |
| `--text-2xl` | 20px | 面板标题 | 建议 |
| `--text-reading` | 15px | 提示词与剧本阅读 | 建议 |
| `--leading-ui` / `--leading-reading` | 1.5 / 1.8 | 界面 / 阅读行高 | 建议 |
| `--weight-regular` / `--weight-strong` | 400 / 600 | 两档字重 | 已接入（时间线） |

依据：实测时间线中有 77 处可见文字小于 11px；画布在「适应全部」时，节点内文字实际只有 4.4–8.5px。

时间线与画布状态栏的映射（阶段 1，D5）：

- 中文标签和文字一律用 `--text-sm`。
- 带中文单位的数字元数据（如「6.00 秒」「图片」类型标记）视为元数据，用 `--text-xs`，并保留等宽数字。
- 比标签高一级的文字用 `--text-md`，例如选中片段名。
- 行高只在固定高度的容器里局部收紧：片段标签 1.25、时长行 1.2，保证 44px 片段内放得下两行。

## 间距、尺寸、圆角、阴影

| Token | 值 | 状态 |
| --- | --- | --- |
| `--space-0-5` … `--space-8` | 2 / 4 / 8 / 12 / 16 / 20 / 24 / 32px | 建议 |
| `--control-dense` | 24px：高密度编辑器的最小点击尺寸 | 建议 |
| `--control-md` / `--control-lg` | 28 / 32px | 建议 |
| `--control-tool` | 38px：画布工具栏 | 建议 |
| `--radius-xs` … `--radius-2xl` | 2 / 4 / 6 / 8 / 12 / 16px | 建议 |
| `--radius-pill` | 9999px，只用于标签 | 建议 |
| `--shadow-popover` | `0 12px 36px #0006, 0 1px 4px #0003` | 已接入（菜单与弹层） |
| `--shadow-panel` | 画布浮动面板现值 | 建议 |
| `--shadow-modal` | `0 28px 100px #0008` | 建议（与 `.modal` 现值相同） |

## 菜单与弹层（阶段 1，D9）

取值来自两个参照组件的实际渲染：命令菜单参照画布右键菜单，内容弹层参照视频参数弹层。宽度、定位、层级、挂载方式和键盘交互仍由各组件自己负责，不做成 Token。

| Token | 值 | 用途 |
| --- | --- | --- |
| `--popover-surface` | `var(--color-surface-raised)` | 菜单和弹层的表面 |
| `--popover-border` | `var(--color-border-strong)` | 1px 描边 |
| `--popover-radius` | 14px | 容器圆角 |
| `--popover-text` | `var(--color-text)` | 正文与菜单项文字 |
| `--popover-padding` | 15px | 内容弹层内边距（参数、选择器） |
| `--menu-padding` | 6px | 命令菜单内边距 |
| `--menu-item-height` | 36px | 菜单项最小高度 |
| `--menu-item-radius` | 8px | 菜单项、列表行圆角 |
| `--menu-item-padding` | `7px 10px` | 菜单项内边距 |
| `--menu-item-gap` | 10px | 图标与文字的间距 |
| `--menu-item-hover` | `var(--color-surface-hover)` | 悬停、展开子菜单；在右键菜单这类方向键移动焦点的菜单里，也表示键盘焦点 |
| `--option-selected-surface` | `var(--color-accent-soft)` | 分段选项、当前项的选中底色 |
| `--option-selected-border` | `var(--color-accent-line)` | 分段选项的选中描边 |

状态规则：

- 危险项文字：`--color-danger`，悬停时底色与普通项相同。
- 键盘焦点：除右键菜单外，其余菜单使用全局的 `--color-focus` 焦点环。右键菜单用方向键移动焦点，焦点由悬停底色表示。
- 禁用：右键菜单的禁用文字 `#747882` 和快捷键文字 `#9297a2` 暂时保留原值，见样式债务 D9。

## 按钮（阶段 1，D9）

组件：`frontend/src/design/Button.tsx`（`Button`、`ButtonLink`、`IconButton`），样式：`frontend/src/design/button.css`。组件只负责类名；可访问名称、`type`、事件、`disabled`、ARIA 属性和 ref 原样传给原生元素，不会补默认的 `type`，表单内的按钮照常提交。

| Token | 值 | 用途 |
| --- | --- | --- |
| `--button-height-md` / `--button-height-sm` | 40px / 32px（`--control-lg`） | 页面和对话框操作 / 紧凑操作 |
| `--button-padding-md` / `--button-padding-sm` | `10px 15px` / `7px 11px` | 内边距 |
| `--button-font-md` / `--button-font-sm` | `--text-md`（13px）/ `--text-sm`（12px） | 字号 |
| `--button-gap` / `--button-radius` | 8px / `--radius-lg`（8px） | 图标间距 / 圆角 |
| `--icon-button-size` / `--icon-button-radius` | `--control-lg`（32px）/ `--radius-md`（6px） | 图标按钮尺寸 / 圆角 |
| `--icon-button-color` | `--color-text-muted` | 图标按钮图形 |
| `--icon-button-hover-color` / `--icon-button-hover-surface` | `--color-text` / `--color-surface-hover` | 图标按钮悬停 |

变体与状态：

| 变体 | 正常 | 悬停 | 禁用 |
| --- | --- | --- | --- |
| 主 `primary` | `--color-accent` 底、`--color-on-accent` 字、600 字重 | `--color-accent-hover` | 共用禁用规则（`states.css`）：中性、不透明、可读 |
| 次 `secondary` | `--color-surface-panel` 底、`--color-border-strong` 描边 | `--color-surface-raised` 底、`--color-text-muted` 描边 | 全局 `button:disabled`（不透明度 .45） |
| 幽灵 `ghost` | 透明、`--color-text-muted` 字 | `--color-surface-hover` 底、`--color-text` 字 | 全局 `button:disabled` |
| 危险 `danger` | `--color-danger-solid` 底、`--color-on-danger-solid` 字 | 不变 | 全局 `button:disabled` |

- 悬停一律带 `:not(:disabled)`，禁用的控件不再有悬停反馈。
- 键盘焦点沿用全局焦点环（`--color-focus`）。
- 悬停上浮动效 `.btn` 不属于组件，由调用方继续传入，去留见样式债务 D10。
- 尺寸：迁移方案曾建议 24 / 28 / 32px 三档。现有页面和对话框操作实际都是 40px，本轮按实际值保留 40 / 32 两档；是否改为 24 / 28 / 32px 需要另行设计决定。
- 图标尺寸由调用方决定。首页卡片沿用 19px 图形；统一为 16px、描边 1.5 的目标尚未执行。

## 层级

数值与阶段 0 之前完全相同，只是有了名字。排序问题见 [样式债务](STYLE-DEBT.md)。

| Token | 值 | 当前使用者 |
| --- | --- | --- |
| `--z-dropdown` | 45 | 画布「更多」菜单 |
| `--z-banner` | 55 | 版本冲突横幅 |
| `--z-notice` | 60 | 画布提示、上传进度、拖放遮罩 |
| `--z-floating` | 80 | 节点搜索、上传面板 |
| `--z-modal` | 100 | 弹窗遮罩、账号弹层 |
| `--z-toast` | 200 | 提示消息 |
| `--z-project-menu` | 1200 | 项目菜单 |
| `--z-media-viewer` | 1500 | 视频查看器 |
| `--z-picker` | 1750 | 参考图选择浮层 |
| `--z-context` | 1800 | 右键菜单、自动编排遮罩、选择横幅、视频参数弹层 |
| `--z-preview` | 1900 | 参考素材预览 |
| `--z-nested-modal` | 2000 | 弹窗内的弹窗 |
| `--z-select` | 2100 | 下拉选择弹层 |
| `--z-image-viewer` | 5000 | 图片大图预览 |

## 动效

| Token | 值 | 状态 |
| --- | --- | --- |
| `--duration-instant` | 90ms | 已接入（`--m-press`） |
| `--duration-fast` | 140ms | 已接入（`--m-in`） |
| `--duration-base` | 200ms | 已接入（`--m-out`） |
| `--ease-out` | `cubic-bezier(.2, .8, .2, 1)` | 已接入（`--m-ease`） |
