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
| `--color-danger` | `#e5735a` | 危险，与品牌色相差 30° 以上 | 建议 |
| `--color-warning` | `#d7ad73` | 警告 | 建议 |
| `--color-info` | `#9ebfe8` | 信息 | 建议 |
| `--color-focus` | 同 accent | 焦点环 | 建议（当前焦点色有 3 种，见样式债务） |

基础色阶 `--ink-*`、`--rose-*` 只在 `tokens.css` 内部引用。

## 文字

| Token | 值 | 用途 | 状态 |
| --- | --- | --- | --- |
| `--font-ui` | Segoe UI, PingFang SC, Microsoft YaHei, system-ui | 界面字体 | 已接入（根元素） |
| `--font-mono` | Cascadia Code, Consolas, Microsoft YaHei, monospace | 路径、代码 | 建议（当前有 4 套等宽字体写法） |
| `--text-xs` | 11px | 数字和英文元数据；不用于中文正文 | 建议 |
| `--text-sm` | 12px | 标签、说明 | 建议 |
| `--text-md` | 13px | 界面正文 | 建议 |
| `--text-lg` | 14px | 强调正文、设置页正文 | 建议 |
| `--text-xl` | 16px | 区块标题 | 建议 |
| `--text-2xl` | 20px | 面板标题 | 建议 |
| `--text-reading` | 15px | 提示词与剧本阅读 | 建议 |
| `--leading-ui` / `--leading-reading` | 1.5 / 1.8 | 界面 / 阅读行高 | 建议 |
| `--weight-regular` / `--weight-strong` | 400 / 600 | 两档字重 | 建议 |

依据：实测时间线中有 77 处可见文字小于 11px；画布在「适应全部」时，节点内文字实际只有 4.4–8.5px。

## 间距、尺寸、圆角、阴影

| Token | 值 | 状态 |
| --- | --- | --- |
| `--space-0-5` … `--space-8` | 2 / 4 / 8 / 12 / 16 / 20 / 24 / 32px | 建议 |
| `--control-dense` | 24px：高密度编辑器的最小点击尺寸 | 建议 |
| `--control-md` / `--control-lg` | 28 / 32px | 建议 |
| `--control-tool` | 38px：画布工具栏 | 建议 |
| `--radius-xs` … `--radius-2xl` | 2 / 4 / 6 / 8 / 12 / 16px | 建议 |
| `--radius-pill` | 9999px，只用于标签 | 建议 |
| `--shadow-popover` | `0 12px 36px #0006, 0 1px 4px #0003` | 建议（与 studio-theme 弹层现值相同） |
| `--shadow-panel` | 画布浮动面板现值 | 建议 |
| `--shadow-modal` | `0 28px 100px #0008` | 建议（与 `.modal` 现值相同） |

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
